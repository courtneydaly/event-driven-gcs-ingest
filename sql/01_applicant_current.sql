-- Latest state per applicant. The daily files are change-data-capture style,
-- so the same applicant appears once per stage change; keep the newest row.
create or replace view `{project}.admissions.applicant_current` as
select * except (rn)
from (
  select
    *,
    row_number() over (partition by applicant_id order by record_updated_at desc) as rn
  from `{project}.raw_admissions.applicant_events`
)
where rn = 1;
