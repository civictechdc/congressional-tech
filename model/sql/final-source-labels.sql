SELECT l.source_id,c.component FROM source_labels l JOIN review_components c ON c.node='c:'||l.component
