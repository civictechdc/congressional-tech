SELECT r.* EXCLUDE(component),c.component FROM recovery_attachments r JOIN review_components c ON c.node='c:'||r.component
