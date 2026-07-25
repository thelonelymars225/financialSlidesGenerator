create policy "deny direct client access"
    on financial_slides.extraction_jobs
    for all
    to anon, authenticated
    using (false)
    with check (false);

create policy "deny direct client access"
    on financial_slides.extraction_sources
    for all
    to anon, authenticated
    using (false)
    with check (false);

create policy "deny direct client access"
    on financial_slides.extraction_results
    for all
    to anon, authenticated
    using (false)
    with check (false);
