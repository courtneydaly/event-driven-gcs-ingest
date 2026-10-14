-- Cohort funnel: applicants grouped by the month they inquired.
-- Counting "reached stage X" (date not null), not current_stage, keeps the
-- funnel monotonic: everyone admitted is also counted as submitted, started, inquired.
create or replace view `{project}.admissions.funnel_by_cohort` as
select
  date_trunc(inquiry_date, month) as inquiry_month,
  term,
  program,
  source_channel,
  count(*)                       as inquiries,
  countif(app_started_date   is not null) as apps_started,
  countif(app_submitted_date is not null) as apps_submitted,
  countif(admitted_date      is not null) as admitted,
  countif(deposited_date     is not null) as deposited
from `{project}.admissions.applicant_current`
group by 1, 2, 3, 4;
