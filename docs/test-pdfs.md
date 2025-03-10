## Instructions to get the PDF files

**⚠️Warning⚠️**
Do not commit users' PDFs to Github


We have two scenarios where the user uploads letters or attachments where Notify converts from RGB to CMYK. CMYK is the supported version for the DVLA printers. Notify-Preview uses Ghostscript, which runs at the OS level by Python subprocess.

When we make any changes to these codes, for example, updating Docker or changing the Ghostscript version or Python code, we are required to go through testing to reduce the risk of transforming a PDF to the incorrect version of DVLA requirements.

Test to consider the following requirements:
- The output PDF file should not exceed the DVLA file size limit.
- It should contain the CMYK format.
- Visually, it should be identical to the original file (e.g., number of pages, colour, fonts).

Since there is a data retention period for the attachments, we are required to find the original and converted attachments and test the new changes for these files. Try to find sample files for different services.

1. [Kibana query](https://kibana.logit.io/s/9423a789-282c-4113-908d-0be3b1bc9d1d/goto/6d9ab46309b12e99f0df00b3e01351f3) allows to filer the letter uploaded to Notify from Admin
- Get the `upload_id` from the message which is the notification id.
- Run the following query to find the details of the output and converted files, update `n.id`
```sql
SELECT n.id, n.service_id, n.reference, n.created_at, la.id FROM notifications n
LEFT JOIN templates t on t.id = n.template_id
LEFT JOIN letter_attachment la ON la.id = t.letter_attachment_id
WHERE n.id = '897a5b0f-91c2-48f6-3456-123ef25d08gh'
```

- Above query should give the notification_id, service_id, reference, created_at and letter_attachment_id. Usually `letter_attachment_id` should be empty because the notification is uploaded letter.
- Original file should be in `S3_BUCKET_PRECOMPILED_ORIGINALS_BACKUP_LETTERS` S3 bucket and search by notification_id.
- Converted (CMKY) file should be in `S3_BUCKET_LETTERS_PDF` S3 bucket and path should be YYYY-MM-DD (use `created_at`) and search by NOTIFY.{reference} (NOTIFY.ABCA8DKABCK9ABC).

2. Attachments to the letter are uploaded from Admin, these attachments are also converted to CMKY format.
- Run the following query to find the uploaded attachments, update the `created_at` filter because original files are deleted after 7 days and change the `LIMIT` if more files are required.
```sql
SELECT DISTINCT la.id AS letter_attachment_id, la.created_at, t.service_id FROM letter_attachment la
RIGHT JOIN templates t ON la.id = t.letter_attachment_id
WHERE la.id IS NOT NULL AND la.created_at > '2025-03-05'
ORDER BY la.created_at DESC
LIMIT 5;
 ```
- Above query should give the letter_attachment_id, created_at and service_id and all the fields should be not null.
- Original File should be in `S3_BUCKET_PRECOMPILED_ORIGINALS_BACKUP_LETTERS` S3 bucket and search by notification_id.
- Converted (CMKY) file should be in `S3_BUCKET_LETTER_ATTACHMENTS` S3 bucket and path should be service-{service_id} (service-897a5b0f-91c2-48f6-3456-123ef25d08gh) and search by letter_attachment_id.
