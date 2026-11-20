-- Hearing print_number per document (ct-n131): constituent granule MODS citation first, then
-- package MODS preferredCitation (preserving ', Part N' when a granule landing page states a part),
-- then the GovInfo Content Details landing page print number when MODS preferredCitation is absent.
SELECT doc_key,print_number FROM (
 SELECT n.doc_key,coalesce(
  mg.print_number,
  CASE WHEN mp.print_number IS NOT NULL AND lp.print_number IS NOT NULL
    AND starts_with(lp.print_number,mp.print_number||', ')
   THEN lp.print_number ELSE mp.print_number END,
  lp.print_number
 ) AS print_number
 FROM landing_page_print_numbers lp RIGHT JOIN (
  gpo_mods_packages mp RIGHT JOIN (
   gpo_mods_granules mg RIGHT JOIN (
    SELECT doc_key,component,
     CASE WHEN starts_with(coalesce(package_id,''),'CHRG-') THEN package_id END AS chrg_package_id,
     CASE WHEN starts_with(coalesce(filename,''),'CHRG-') THEN regexp_replace(filename,'[.][^.]+$','') END AS chrg_stem
    FROM base_normalized
   ) n ON mg.granule_id=n.chrg_stem
  ) ON mp.package_id=n.chrg_package_id
 ) ON lp.component=n.component
) WHERE print_number IS NOT NULL
