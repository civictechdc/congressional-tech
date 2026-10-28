SELECT r.recovery_id,'invalid_recovery_attachment' AS error FROM model_recovery_rows r
LEFT JOIN recovery_attachments a ON r.recovery_id=a.recovery_id
GROUP BY r.recovery_id HAVING count(a.component)<>1
