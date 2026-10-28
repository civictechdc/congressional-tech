SELECT r.* FROM readings r JOIN parser_versions v ON r.parser=v.parser AND r.parser_version=v.version
