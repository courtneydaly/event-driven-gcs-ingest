-- Each query should return zero rows. Schedule them, or run them after loads.

-- 1. Funnel must be nested: a later stage implies every earlier one.
select applicant_id, 'stage skipped' as issue
from `{project}.admissions.applicant_current`
where (app_submitted_date is not null and app_started_date   is null)
   or (admitted_date      is not null and app_submitted_date is null)
   or (deposited_date     is not null and admitted_date      is null)

union all

-- 2. Stage dates never go backwards.
select applicant_id, 'dates out of order'
from `{project}.admissions.applicant_current`
where app_started_date   < inquiry_date
   or app_submitted_date < app_started_date
   or admitted_date      < app_submitted_date
   or deposited_date     < admitted_date

union all

-- 3. Cohort counts are monotonic (catches double-counting in the view itself).
select cast(inquiry_month as string), 'non-monotonic funnel'
from `{project}.admissions.funnel_by_cohort`
where apps_started > inquiries or apps_submitted > apps_started
   or admitted > apps_submitted or deposited > admitted;
