# Deploying

Follow the guidance below when deploying changes that affect the:

- [generation](#changes-to-pdf-generation)
- [validation](#changes-to-pdf-validation) or
- [preview](#changes-to-previewing-pdfs) of PDFs.

The aim of the guidance is to help minimise risk for these kinds of changes.

## Changes to PDF generation

The real-world variability of PDFs isn't represented in the test suite*. A PDF can also appear to be visually OK but cause problems when combined with other PDFs in a print run.

_*In a typical hour we see PDFs produced by e.g. PDFsharp, LibreOffice, PDFKit, pdf-lib, Microsoft® Word, Microsoft: Print To PDF, Adobe Acrobat. There are also many others._

### Manual testing

Test the output looks visually OK before / after with a few sample PDFs. You should consider [tweaking the code](https://github.com/alphagov/notifications-template-preview/commit/73b0b557429fad7a1280a691b583bf8d9c569d9c) so you can force any PDF through the full gamut of processing we may do to it.

```bash
# reproduce changes without making a commit
git cherry-pick -n 73b0b557429fad7a1280a691b583bf8d9c569d9c
```

[Remember to run `make bootstrap-with-docker`](https://github.com/alphagov/notifications-template-preview#docker-container) if switching between versions of dependencies. If you don't, the code will run with an out-of-date image, using old / random dependencies.

Example command to test a PDF:

```python
# run in a flask shell
from app.precompiled import sanitise_file_contents
import base64

def convert(name, prefix):
  out = sanitise_file_contents(open(f'tests/test_pdfs/{name}.pdf', 'rb').read(), allow_international_letters=True, filename='foo')
  open(f'{prefix}_{name}.pdf', 'wb').write(base64.b64decode(out['file'].encode('utf-8')))
```

Suggested PDFs to test with:

```python
names = [
  'no_colour',
  'example_dwp_pdf',
  'public_guardian_sample',
  'address_block_repeated_on_second_page',
  'landscape_rotated_page'
]

# similarly for 'after' your change
for name in names: convert(name, 'before')
```

It can be helpful to open the before / after PDFs in a web browser, so you can quickly tab back and forth between them and spot any minor changes in doing so.

### Test deployment

[Deploy the branch manually](https://github.com/alphagov/notifications-manuals/wiki/Merging-and-deploying#docker-apps-antivirus-template-preview) to Production.

- Suggested deployment window: 4PM to 5PM.
- Don't do it on a Friday.
- Send a courtesy email to our print provider.

This means any problems caused by the test deployment are contained in a single print run. Doing it later in the day should also avoid the bulk of the traffic and minimise any impact.

During the test deployment, monitor:

- Grafana for 4xx / 5xx (for the `notify-template-preview` app).
- Statuses in the DB (for the`notify-template-preview-celery` app).

Query to check for letter statuses:

```sql
select date_trunc('hour', created_at) as created_after, notification_status, count(*) from notifications
where notification_type='letter'
and created_at > '2021-11-25 12:00'
and created_at < '2021-11-25 17:00'
and key_type != 'test'
group by 1,2
order by 2,1;
```

As an extra step, you can also look at the distribution of validation failures within before / during the test deploy window. This requires a bit of hacky data crunching with CloudWatch.

```
# set the time range for the query to e.g. 1 week

fields @timestamp, @message
| filter levelname == "ERROR" or levelname == "WARNING"
| parse message /([^\.:]+:)?(?<error>[^\.,0-9]+)/
| stats count(*) by error, bin(1d) as day
| sort error, day desc
```

The `parse` regex tries to strip out IDs and fluff so the results easier to group and visually scan. Compare the results line by line, for each error / day, to check for new errors or significant increases.

### Extended deployment

Before deploying again, wait until you have delivery receipts for all letters created during the test deploy. Even if a few are still `sending`, it's worth waiting to find out if they are symptoms of a problem.

```sql
select date_trunc('hour', created_at) as created_after, notification_status, count(*) from notifications
where notification_type='letter'
and created_at > '2021-11-25 12:00'
and created_at < '2021-11-25 17:00'
and key_type != 'test'
group by 1,2
order by 2,1;
```

It's also worth checking which types of PDF were covered by the test deploy. This can inform whether a longer test deploy would be worthwhile. You can use CloudFront to extract this information:

```
fields @timestamp, @message
| filter message like "Processing letter"
| parse message 'Processing letter "*" with creator "*" and producer "*"' as letter, creator, producer
| stats count(*) as count by creator, producer
| sort count desc
```

To compare with historial data:

1. Set the time range to the previous day / week.
2. Do "Export results", "Copy csv to clipboard".
3. Paste into a Google Sheet and [split into columns](https://support.google.com/docs/answer/6325535).
4. Repeat for the test time range in the same sheet.
5. Select both "Producer" and both "count" columns.
6. Create a graph to visualise the Producer data.
7. Repeat for the Creator data.

Google Sheets automatically shows both series on the same graph, so you can compare volumes. Check if the test covered smaller Creators / Producers e.g. Microsoft Word, Adobe Acrobat.

## Changes to PDF validation

Our automated tests cover the known cases where we expect a letter to pass or fail our validations. However, it's still possible a change may lead to PDFs passing or failing when they shouldn't:

- We could start rejecting lots of PDFs. This isn't a disaster: a user can always re-upload a letter we've incorrectly rejected, after we fix the issue / rollback.

- We could start accepting too many PDFs. This may only become apparent when our print provider or potentially recipients (if the letter was gibberish) complain.

Follow the deployment sections for "Changes to PDF generation".

## Changes to previewing PDFs

This isn't critical, so long as it works and doesn't differ much from the generated PDF. In the past we've found [there can be subtle before / after differences that aren't present in the PDF itself](https://github.com/alphagov/notifications-template-preview/pull/591#issuecomment-979284671).

It's sufficient to test with one or two example PDFs e.g.

- public_guardian_sample.pdf
- example_dwp_pdf.pdf

It doesn't matter if the validations pass or fail here: [the preview is the same either way](https://github.com/alphagov/notifications-admin/blob/5e8d0623de85eb0b10572635cdfc15ff6f35db32/app/templates/views/uploads/preview.html#L48).
