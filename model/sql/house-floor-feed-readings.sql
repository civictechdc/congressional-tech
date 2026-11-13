-- Derived feed rows retain entry revisions separately from document prose.
-- selected_readings already restricts each parser to its accepted current pin.
SELECT * FROM selected_readings
WHERE parser='house_floor_feed' AND status='completed'
