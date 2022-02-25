# Deploying

Follow the guidance below when deploying major changes that affect the generation or validation of PDFs. You may also need to do some [visual testing](visual-testing.md), depending on the change.

## Why we need this guidance

The real-world variability of PDFs isn't represented in the test suite*. A PDF can also appear to be visually OK but cause problems when combined with other PDFs in a print run:

- We could send our print provider valid PDFs which the new version of the code has corrupted so they won't print or need to be printed individually / manually.

- We could start rejecting lots of PDFs. This isn't a disaster: a user can always re-upload a letter we've incorrectly rejected, after we fix the issue / rollback.

- We could start accepting too many PDFs. This may only become apparent when our print provider or potentially recipients (if the letter was gibberish) complain.

_*In a typical hour we see PDFs produced by e.g. PDFsharp, LibreOffice, PDFKit, pdf-lib, Microsoft® Word, Microsoft: Print To PDF, Adobe Acrobat. There are also many others._

## Suggested deployment steps

### Test deployment

[Deploy the branch manually](https://github.com/alphagov/notifications-manuals/wiki/Merging-and-deploying#docker-apps-antivirus-template-preview) to Production.

- Suggested deployment window: 1 hour, no later than 4PM.
- Don't do it on a Friday.
- Send a courtesy email to our print provider.

This means any problems caused by the test deployment are contained in a single print run. Traffic isn't significantly lower at any time during working hours, so pick an hour that suits you.

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

Before deploying again, wait until you have delivery receipts for all letters created during the test deploy. Even if a few are still `sending`, it's worth waiting to find out if they are symptoms of a problem.

### Optional step: validation analysis

You can also look at the distribution of validation failures before / during the test deploy window. This requires a bit of hacky data crunching with CloudWatch.

```
# set the time range for the query to e.g. 1 week

fields @timestamp, @message
| filter levelname == "ERROR" or levelname == "WARNING"
| parse message /([^\.:]+:)?(?<error>[^\.,0-9]+)/
| stats count(*) by error, bin(1d) as day
| sort error, day desc
```

The `parse` regex tries to strip out IDs and fluff so the results easier to group and visually scan. Compare the results line by line, for each error / day, to check for new errors or significant increases.

### Optional step: coverage analysis

It's worth checking which types of PDF were covered by the test deploy. This can inform whether a longer test deploy would be worthwhile. You can use CloudFront to extract this information:

```
fields @timestamp, @message
| filter message like "Processing letter"
| parse message 'Processing letter "*" with creator "*" and producer "*"' as letter, creator, producer
| stats count(*) as count by producer
| sort count desc
```

Set the time range to the trial deployment window and repeat for a longer period e.g. a week. A visual comparison may suffice, or you can do [a spreadsheet like this one to thoroughly check coverage](https://docs.google.com/spreadsheets/d/1U2W80usGVXB3rOQg7mJBfUswRSulT7uGsxFnnVN_hiI/edit#gid=0).

Repeat the analysis for "creator", as [both of these properties could have an impact](https://tex.stackexchange.com/questions/590864/pdfcreator-vs-pdfproducer-pdf-metadata-in-hyperref-hypersetup#:~:text=according%20to%20the%20pdf%20reference,%3DWord%2C%20Producer%3Dprinttopdf).

Normally we'd expect over 90% coverage.

### Extended deployment

