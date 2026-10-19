"""Corpus recovery modules used after the workspace is installed.

Import operations from their owning module. Keep package import free of archive
implementation imports: publication admission runs before --runtime selects the
catalog implementation from its named checkout.
"""
