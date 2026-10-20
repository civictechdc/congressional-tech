/** One maintained typed-details to original-field policy for both readers. */
export function decodeDetailRecord(data) {
    const {filename_readings, fact_alternatives, filename_field_count, ...record} = data;
    const facts = {};
    for (const name of ['http_status','response_usable','response_body_complete','record_role','state_checked_at','state_retrieved_at']) {
      if (!(name in record)) continue;
      facts[name] = record[name];
      record[name] = record[name] == null ? null : [String(record[name])];
    }
    for (const item of fact_alternatives || []) record[item.field] = item.values;
    for (const item of filename_readings || []) record[item.field] = item.values;
    facts.completeness_conflict = new Set(record.response_body_complete || []).size > 1;
    return {record, facts, filename_field_count};
}
