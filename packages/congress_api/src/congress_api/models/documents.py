"""Typed readings of witness-list documents, with original bytes and source text."""
from typing import Annotated

from pydantic import Field, model_validator

from .base import SourceModel
from .content import RawContent


class DocumentWitness(SourceModel):
    name: str
    honorific: str = ''
    position: str = ''
    organization: str = ''


class ReviewedPdfReading(SourceModel):
    url: str
    page: int = Field(ge=1)
    pages: list[Annotated[int, Field(ge=1)]] | None = None
    text: str
    basis: str
    reviewed_on: str


class PdfTextPage(SourceModel):
    number: int = Field(ge=1)
    text: str


class PdfWitnessObservation(SourceModel):
    people: list[DocumentWitness]
    text_present: bool
    source_text: str
    raw_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    parser_version: int = Field(ge=1)
    reviewed_reading: ReviewedPdfReading | None = None
    content: RawContent
    pages: list[PdfTextPage]

    @model_validator(mode='after')
    def check_reading(self):
        if self.content.sha256 != self.raw_sha256:
            raise ValueError('PDF observation and raw content digest mismatch')
        if self.text_present != bool(self.source_text.strip()):
            raise ValueError('text_present must describe the retained extracted source text')
        if self.source_text != '\n'.join(page.text for page in self.pages):
            raise ValueError('PDF source_text must retain every extracted page in order')
        return self


class ModsWitnessObservation(SourceModel):
    people: list[DocumentWitness]
    source_witnesses: list[str]
    raw_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    parser_version: int = Field(ge=1)
    content: RawContent

    @model_validator(mode='after')
    def check_digest(self):
        if self.content.sha256 != self.raw_sha256:
            raise ValueError('MODS witness observation and raw content digest mismatch')
        return self
