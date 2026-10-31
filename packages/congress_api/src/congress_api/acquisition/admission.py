"""Durable, atomic admission for campaign network calls.

Costs are integer microdollars. An unknown outcome retains its reservation until
an operator reconciles it against provider evidence.
"""
from contextlib import contextmanager
import sqlite3
from uuid import uuid4


class AdmissionDenied(RuntimeError):
    pass


class Admission:
    def __init__(self, path, request_cap, spend_cap):
        if type(request_cap) is not int or request_cap < 0 or type(spend_cap) is not int or spend_cap < 0:
            raise ValueError('Admission caps must be nonnegative integers')
        self.path, self.request_cap, self.spend_cap = str(path), request_cap, spend_cap
        with self._connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id TEXT PRIMARY KEY, kind TEXT NOT NULL, upper_cost INTEGER NOT NULL, actual_cost INTEGER, status TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS limits (request_cap INTEGER NOT NULL, spend_cap INTEGER NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            limits=db.execute('SELECT request_cap,spend_cap FROM limits').fetchone()
            if limits is None:
                db.execute('INSERT INTO limits VALUES (?,?)',(request_cap,spend_cap))
            elif limits != (request_cap,spend_cap):
                raise ValueError('Admission caps differ from the durable campaign limits')
            db.commit()

    @contextmanager
    def _connect(self):
        db=sqlite3.connect(self.path,timeout=30,isolation_level=None)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:yield db
        finally:db.close()

    def reserve(self, kind, upper_cost):
        if not isinstance(kind,str) or not kind or type(upper_cost) is not int or upper_cost < 0:
            raise ValueError('An attempt needs a kind and a nonnegative cost bound')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            requests,spent=db.execute("SELECT count(*),coalesce(sum(CASE WHEN status='settled' THEN actual_cost ELSE upper_cost END),0) FROM attempts").fetchone()
            if requests >= self.request_cap or spent + upper_cost > self.spend_cap:
                db.rollback()
                raise AdmissionDenied('Campaign request or spend cap exhausted')
            attempt_id=uuid4().hex
            db.execute("INSERT INTO attempts VALUES (?,?,?,NULL,'reserved')",(attempt_id,kind,upper_cost))
            db.commit()
            return attempt_id

    def settle(self, attempt_id, actual_cost):
        if type(actual_cost) is not int or actual_cost < 0:
            raise ValueError('Actual cost must be a nonnegative integer')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT upper_cost,actual_cost,status FROM attempts WHERE id=?',(attempt_id,)).fetchone()
            if row is None or actual_cost > row[0] or (row[2]=='settled' and row[1]!=actual_cost):
                db.rollback()
                raise ValueError('Invalid admission settlement')
            db.execute("UPDATE attempts SET actual_cost=?, status='settled' WHERE id=?",(actual_cost,attempt_id))
            db.commit()

    def totals(self):
        with self._connect() as db:
            requests,spent,unknown=db.execute("SELECT count(*),coalesce(sum(CASE WHEN status='settled' THEN actual_cost ELSE upper_cost END),0),coalesce(sum(CASE WHEN status='reserved' THEN 1 ELSE 0 END),0) FROM attempts").fetchone()
        return dict(requests=requests,committed_cost=spent,unknown=unknown)
