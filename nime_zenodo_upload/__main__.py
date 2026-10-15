########################################################
'''
Written by Benedikte Wallace, 2018, edited by Charles Martin, 2024, and Stefano Fasciani 2025-2026.

This script reads .bib files in NIME archive and creates a deposition record
on the Zenodo website. The metadata from the .bib entries are tied to the
article (.pdf file) and are published to Zenodo resulting in the creation
of a DOI. When this script is used to upload a new batch of papers the DOI
and file name of each paper are added to the text file nime_dois.txt.

Supplementary files:

If a resource contains supplementary files that should be uploaded together with the paper, each
supplementary file should have the same base file name as the paper PDF with an additional
suffix such as _file01, _file02, etc., appended before the extension, e.g.:

    nime2025_10.pdf
    nime2025_10_file01.mp4
    nime2025_10_file02.mov

Supplementary files larger than 100 MB are skipped by this script: they are NOT uploaded via
the API. The script:
  - prints a warning for each skipped file,
  - marks the corresponding DOI line in nime_dois.txt by appending "*" followed by a ";"-separated
    list of skipped filenames, so they can be uploaded manually via the Zenodo web UI.

Zenodo displays files alphabetically in its UI.
'''
########################################################


import json
import requests
import datetime
#import latexcodec # TODO: remove this.
import click
import os
import tomllib
import pprint
import time

from pybtex.database.input import bibtex

# Bibtex parser
parser = bibtex.Parser()

UPLOAD_FOLDER = './upload/'
CONFERENCE_TITLE = 'International Conference on New Interfaces for Musical Expression'
CONFERENCE_ACRONYM = 'NIME'

# Maximum size for automatic supplementary upload (100 MB)
MAX_SUPP_BYTES = 100 * 1024 * 1024
# Maximum size for PDF upload (100 MB) – PDFs over this limit will abort the whole run.
MAX_PDF_BYTES = 100 * 1024 * 1024

# New dois and file names are appended to nime_dois.txt (production) or
# nime_dois_sandbox.txt (sandbox), so sandbox runs never mark production entries as done.
DOI_FILENAME = "nime_dois.txt"
SANDBOX_DOI_FILENAME = "nime_dois_sandbox.txt"

# Zenodo sometimes answers slowly or with 5xx errors (e.g. 504 Gateway Time-out).
REQUEST_TIMEOUT = 300  # seconds
RETRIES = 5
RETRY_WAIT = 10  # seconds, doubled after each attempt

# Tokens, replace with public and sandbox tokens from Zenodo:
with open("secrets.toml", "rb") as f:
    secret_data = tomllib.load(f)


class UploadError(Exception):
    """An upload step failed and its outcome on Zenodo could not be confirmed."""


def doi_filename(production_zenodo):
    return DOI_FILENAME if production_zenodo else SANDBOX_DOI_FILENAME


def recorded_pdfs(production_zenodo):
    """Return the PDF filenames that already have a DOI line in the DOI file."""
    try:
        with open(doi_filename(production_zenodo)) as doi_file:
            return {line.split(',', 1)[0] for line in doi_file if ',' in line}
    except FileNotFoundError:
        return set()


def _get_with_retries(url, token):
    """GET a Zenodo API url, retrying on connection errors and 5xx responses.

    Only used for reads, which are safe to repeat.
    """
    wait = RETRY_WAIT
    problem = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(url, params={'access_token': token}, timeout=REQUEST_TIMEOUT)
            if resp.status_code < 500:
                return resp
            problem = f"status code {resp.status_code}"
        except requests.RequestException as e:
            problem = str(e)
        if attempt < RETRIES:
            click.secho(f"GET {url} failed ({problem}), retrying in {wait} s", fg='yellow')
            time.sleep(wait)
            wait *= 2
    raise UploadError(f"GET {url} failed {RETRIES} times, last: {problem}")


def _print_response_json_or_text(resp, color='red'):
    """Helper to print a requests.Response as JSON if possible, otherwise as raw text."""
    try:
        data = resp.json()
        click.secho(data, fg=color)
    except ValueError:
        # Not JSON (e.g., HTML 413 page); print raw text
        click.secho(resp.text, fg=color)


def upload_to_zenodo(metadata, pdf_path, production_zenodo=False, add_title=False):
    '''
    upload(metadata, pdf_path):
    - connects to zenodo REST API,
    - creates a new record,
    - enters metadata,
    - uploads the .pdf and supplementary files
    - publishes it
    '''

    if production_zenodo:
        ZENODO_URL = 'https://zenodo.org'
        TOKEN = secret_data['PUBLIC_TOKEN']  # either SANDBOX_TOKEN or PUBLIC_TOKEN
    else:
        ZENODO_URL = 'https://sandbox.zenodo.org'
        TOKEN = secret_data['SANDBOX_TOKEN']

    # Track supplementary files that were too large or otherwise skipped
    skipped_supplementary = []

    click.secho(f"Starting new upload for: {pdf_path} to {ZENODO_URL}", fg='yellow')
    url = ZENODO_URL + '/api/deposit/depositions'
    access_depositions = _get_with_retries(url, TOKEN)
    click.secho(f"Access depositions: {access_depositions.status_code}", fg='yellow')

    # Create new paper submission - add parsed metadata.
    # Not retried: a request that timed out may still have created a deposition.
    headers = {"Content-Type": "application/json"}
    try:
        new_deposition = requests.post(
            url,
            params={'access_token': TOKEN},
            json=metadata,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as e:
        raise UploadError(
            f"Creating the deposition for {pdf_path} failed ({e}). "
            f"Check {ZENODO_URL}/me/uploads for an unpublished draft and delete it before re-running."
        )

    # If creation of new deposition is unsuccessful, abort
    if new_deposition.status_code > 210:
        click.secho(
            f"Error happened during submission {pdf_path}, status code: "
            f"{new_deposition.status_code}",
            fg='red'
        )
        _print_response_json_or_text(new_deposition, color='red')
        raise UploadError(
            f"Creating the deposition for {pdf_path} failed. "
            f"Check {ZENODO_URL}/me/uploads for an unpublished draft and delete it before re-running."
        )

    submission_id = json.loads(new_deposition.text)["id"]

    # Upload the pdf file
    url_files = (
        ZENODO_URL +
        "/api/deposit/depositions/{id}/files?access_token={token}".format(
            id=str(submission_id),
            token=TOKEN
        )
    )
    upload_metadata = {'filename': pdf_path}
    pdf_full_path = os.path.join(UPLOAD_FOLDER, pdf_path)
    try:
        with open(pdf_full_path, 'rb') as pdf_file:
            add_file = requests.post(
                url_files, data=upload_metadata, files={'file': pdf_file}, timeout=REQUEST_TIMEOUT
            )
    except requests.RequestException as e:
        raise UploadError(
            f"Uploading {pdf_path} to draft {submission_id} failed ({e}). "
            f"Delete the draft at {ZENODO_URL}/me/uploads before re-running."
        )

    # If upload of file is unsuccessful, abort
    if add_file.status_code > 210:
        click.secho(
            f"Error happened during file upload of {pdf_path}, status code: "
            f"{add_file.status_code}",
            fg='red'
        )
        _print_response_json_or_text(add_file, color='red')
        raise UploadError(
            f"Uploading {pdf_path} to draft {submission_id} failed. "
            f"Delete the draft at {ZENODO_URL}/me/uploads before re-running."
        )

    # Upload supplementary files (if any)
    all_files = os.listdir(UPLOAD_FOLDER)
    pdf_fname_prefix = pdf_path[:-4] + "_"
    matching_files = [file for file in all_files if file.startswith(pdf_fname_prefix)]

    for extra_file_path in matching_files:
        if extra_file_path == pdf_path:
            continue

        full_extra_path = os.path.join(UPLOAD_FOLDER, extra_file_path)
        file_size = os.path.getsize(full_extra_path)

        # Pre-check size: skip if over MAX_SUPP_BYTES
        if file_size > MAX_SUPP_BYTES:
            click.secho(
                f"Skipping supplementary file {extra_file_path} "
                f"({file_size / (1024 * 1024):.1f} MB) – above automatic upload limit "
                f"({MAX_SUPP_BYTES / (1024 * 1024):.0f} MB).",
                fg='yellow'
            )
            click.secho(
                "Upload this file manually via the Zenodo web UI and attach it to the deposition.",
                fg='yellow'
            )
            skipped_supplementary.append(extra_file_path)
            continue

        click.secho(
            f"Starting upload for supplementary file: {extra_file_path} to {ZENODO_URL}",
            fg='yellow'
        )
        upload_metadata = {'filename': extra_file_path}
        try:
            with open(full_extra_path, 'rb') as extra_file:
                add_file = requests.post(
                    url_files, data=upload_metadata, files={'file': extra_file},
                    timeout=REQUEST_TIMEOUT
                )
        except requests.RequestException as e:
            click.secho(f"Supplementary file upload of {extra_file_path} failed: {e}", fg='red')
            skipped_supplementary.append(extra_file_path)
            continue

        # If upload of file is unsuccessful, warn and continue
        if add_file.status_code > 210:
            click.secho(
                f"Error happened during supplementary file upload of {extra_file_path}, "
                f"status code: {add_file.status_code}",
                fg='red'
            )

            if add_file.status_code == 413:
                click.secho(
                    "Server reports the file is too large (HTTP 413). "
                    "You must upload this file manually via the Zenodo web UI.",
                    fg='red'
                )

            _print_response_json_or_text(add_file, color='red')
            skipped_supplementary.append(extra_file_path)
            # Do not abort the whole deposition; continue with other files
            continue

    click.secho(f"{pdf_path} submitted with ID {submission_id}", fg='green')

    # publish the new deposition
    deposition_url = f"{ZENODO_URL}/api/deposit/depositions/{submission_id}"
    try:
        publish_record = requests.post(
            f"{deposition_url}/actions/publish",
            params={'access_token': TOKEN},
            timeout=REQUEST_TIMEOUT
        )
        publish_problem = None if publish_record.status_code <= 210 else publish_record.status_code
    except requests.RequestException as e:
        publish_record = None
        publish_problem = e

    # get back the deposition to confirm it was published and read the DOI.
    # A publish that errored (e.g. 504) may still have gone through on Zenodo.
    retrieved_deposition = _get_with_retries(deposition_url, TOKEN)
    try:
        deposition = retrieved_deposition.json()
    except ValueError:
        deposition = {}
    published = deposition.get('submitted') and deposition.get('state') == 'done'

    if publish_problem is not None:
        click.secho(f"Error happened during publish: {publish_problem}", fg='red')
        if publish_record is not None:
            _print_response_json_or_text(publish_record, color='red')
        if not published:
            raise UploadError(
                f"Publishing {pdf_path} (deposition {submission_id}) failed. It is an unpublished "
                f"draft: publish or delete it at {ZENODO_URL}/me/uploads, and if you publish it, "
                f"add its DOI line to {doi_filename(production_zenodo)} before re-running."
            )
        click.secho(f"...but deposition {submission_id} was published anyway.", fg='yellow')
    elif not published:
        raise UploadError(
            f"Zenodo accepted the publish of {pdf_path} but deposition {submission_id} "
            f"does not show as published. Check it at {ZENODO_URL}/me/uploads."
        )
    click.secho(f"{pdf_path} PUBLISHED with ID {submission_id}", fg='green')

    retrieved_doi = deposition.get('doi')
    if not retrieved_doi:
        raise UploadError(f"Deposition {submission_id} for {pdf_path} is published but has no DOI.")
    click.secho(f"{pdf_path} confirmed DOI is {retrieved_doi}", fg='green')

    # If any supplementary files were skipped, mark DOI and record filenames.
    # We use ';' as separator for multiple filenames so the line remains valid CSV.
    doi_field = retrieved_doi
    if skipped_supplementary:
        skipped_list = ';'.join(skipped_supplementary)
        doi_field = f"{retrieved_doi}*{skipped_list}"
        click.secho(
            f"Supplementary files skipped for {pdf_path}: {skipped_list}. "
            f"Marked DOI as {doi_field} in {doi_filename(production_zenodo)}.",
            fg='yellow'
        )

    # Record in the csv file.
    # With --title:  pdf_path,submission_id,doi_field,title
    # Without --title: pdf_path,submission_id,doi_field
    if add_title:
        title = metadata.get('metadata', {}).get('title', '')
        if title is None:
            title = ''
        title = str(title).replace('\n', ' ').strip()
        line = f'{pdf_path},{submission_id},{doi_field},{title}\n'
    else:
        line = f'{pdf_path},{submission_id},{doi_field}\n'

    with open(doi_filename(production_zenodo), 'a') as doi_file:
        doi_file.write(line)


def format_metadata(
    bibfilename,
    verbose=False,
    upload_pdf=False,
    print_authors=False,
    production_zenodo=False,
    add_title=False,
    publication_date=None,
    conference_dates=None
):
    '''
    format_metadata(bibfilename):
    - formats contents of entries in the .bib file referenced by bibfilename
    - for each entry, metadata is formatted and the upload function
      above is called in order to publish record
    '''
    bibdata = parser.parse_file(bibfilename)

    # If we are going to upload PDFs, pre-check that none of them exceed MAX_PDF_BYTES.
    if upload_pdf:
        oversized_pdfs = []
        missing_pdfs = []
        for bib_id in bibdata.entries:
            b = bibdata.entries[bib_id].fields
            try:
                conf_url = b['Url']
                pdf_name = conf_url.rsplit('/', 1)[-1]
                pdf_path = os.path.join(UPLOAD_FOLDER, pdf_name)

                if not os.path.exists(pdf_path):
                    missing_pdfs.append(pdf_name)
                    continue

                size = os.path.getsize(pdf_path)
                if size > MAX_PDF_BYTES:
                    oversized_pdfs.append((pdf_name, size))
            except KeyError:
                # If Url is missing, this entry will fail later anyway; let the normal logic handle it.
                continue

        if missing_pdfs:
            click.secho(
                "The following PDFs referenced in the .bib file do not exist in the upload folder:",
                fg='red'
            )
            for name in sorted(set(missing_pdfs)):
                click.secho(f"  - {name}", fg='red')
            click.secho(
                "Fix the missing files before running the upload.",
                fg='red'
            )
            # Abort before any upload.
            return

        if oversized_pdfs:
            click.secho(
                "One or more PDFs are larger than 100 MB and will fail to upload:",
                fg='red'
            )
            for name, size in sorted(set(oversized_pdfs)):
                click.secho(
                    f"  - {name}: {size / (1024 * 1024):.1f} MB",
                    fg='red'
                )
            click.secho(
                "Zenodo rejects these large PDF uploads (HTTP 413). "
                "Please compress or split these PDFs to be under 100 MB and try again.",
                fg='red'
            )
            click.secho(
                "Aborting before starting any uploads. No Zenodo records were created.",
                fg='red'
            )
            return

    title = 'title'
    abstract = 'abstract'
    address = 'address'
    creators = 'creators'
    pubdate = '20XX-06-01'
    pages = 'x-x'
    conf_url = ''
    pdf_name = ''
    creators = []

    # loop through the individual entries
    for bib_id in bibdata.entries:
        title = 'title'
        abstract = 'abstract'
        address = 'address'
        creators = 'creators'
        pubdate = '20XX-06-01'
        pages = 'x-x'
        conf_url = ''
        pdf_name = ''
        creators = []

        b = bibdata.entries[bib_id].fields
        try:
            conf_url = b['Url']
            pdf_name = conf_url.rsplit('/', 1)[-1]

            if not os.path.exists(UPLOAD_FOLDER + pdf_name):
                click.secho(f'PDF: {pdf_name} does not exist in the upload folder!', fg='red')
                raise Exception(f'The PDF {pdf_name} did not exist in the upload folder.')

            title = b['Title']
            for author in bibdata.entries[bib_id].persons["Author"]:
                author_name = str(author)
                # TODO: would be better to use https://github.com/phfaist/pylatexenc
                # author_name = bytes(author_name,"utf-8").decode("latex","ignore")
                author_name = author_name.replace("}", "")
                author_name = author_name.replace("{", "")
                author_name = author_name.replace("\\\"", "")
                creators.append({'name': author_name})
                if print_authors:
                    pprint.pp(author_name)

            yr_seg = conf_url.rsplit('/', 1)[-2]
            yr = yr_seg.rsplit('/', 1)[-1]
            pubdate = yr + pubdate[4:]

            address = b.get('Address', 'Address')
            pages = b.get('Pages', None)
            abstract = b.get('Abstract', '---')  # if no abstract is found, --- will be used as default
            track = b.get('track')  # could be used for conference_session key
            partof_title = b.get('booktitle')
            conf_session = b.get('note', None)
            isbn = b.get('isbn')
            issn = b.get('issn')

            # Build base metadata
            data = {
                'metadata': {
                    'title': title,
                    'upload_type': 'publication',
                    'publication_type': 'conferencepaper',
                    'description': abstract,
                    'conference_title': CONFERENCE_TITLE,
                    'conference_acronym': CONFERENCE_ACRONYM,
                    'conference_dates': conference_dates,
                    'conference_place': address,
                    'conference_url': 'https://nime.org',
                    'publication_date': publication_date,
                    'partof_title': partof_title,
                    'imprint_title': partof_title,
                    'creators': creators,
                    'communities': [{'identifier': 'nime_conference'}],  # adds to Zenodo NIME community
                    'imprint_isbn': isbn,
                    'imprint_issn': issn
                }
            }

            # Pass ISSN to Zenodo "Related works → Is part of" via related_identifiers
            if issn:
                # This will show up under "Additional details → Related works → Is part of"
                data['metadata']['related_identifiers'] = [
                    {
                        'identifier': issn,
                        'relation': 'isPartOf',
                        'resource_type': 'journal-issn'
                    }
                ]

            if conf_session is not None:
                data['metadata']['conference_session'] = conf_session

            if pages is not None:
                data['metadata']['partof_pages'] = pages

            if verbose:
                pprint.pp(data['metadata'])

            if upload_pdf:
                if pdf_name in recorded_pdfs(production_zenodo):
                    click.secho(
                        f"Skipping {pdf_name}: already in {doi_filename(production_zenodo)}",
                        fg='cyan'
                    )
                    continue
                upload_to_zenodo(
                    data,
                    pdf_name,
                    production_zenodo=production_zenodo,
                    add_title=add_title
                )

        except (KeyError):
            # TODO Write failed bib ID's to a text file?
            print("KeyError! Entry did not contain fields needed, continuing to next id - failed bib id: ", bib_id)
            raise


def conference_options(f):
    """Required options for the conference edition being uploaded."""
    f = click.option(
        '--conference-dates',
        required=True,
        help="Dates of the conference, e.g. '23 June - 26 June, 2026'."
    )(f)
    f = click.option(
        '--publication-date',
        required=True,
        type=click.DateTime(formats=['%Y-%m-%d']),
        help='Publication date of the proceedings, YYYY-MM-DD.'
    )(f)
    return f


@click.command()
@click.argument('bibfile', type=click.Path(exists=True))
@conference_options
@click.option('--production', is_flag=True)
@click.option(
    '--title',
    'include_title',
    is_flag=True,
    help='Also append the paper title as the last field in nime_dois.txt'
)
def upload(bibfile, publication_date, conference_dates, production, include_title):
    """Process metadata from a .bibtex file and upload to Zenodo."""
    publication_date = publication_date.strftime('%Y-%m-%d')
    click.secho(
        f"Publication date: {publication_date}, conference dates: {conference_dates}",
        fg="yellow"
    )
    if production:
        click.secho(
            "WARNING! You are uploading to the production Zenodo server! "
            "Make sure you are ready! Cancel if not!",
            fg="red"
        )
    else:
        click.secho(
            "You are uploading to the sandbox Zenodo server! Test here as much as you want.",
            fg="green"
        )
    input("Press Enter to continue or Ctrl-C to abort.")
    # Add date and time for this upload
    with open(doi_filename(production), 'a') as doi_file:
        doi_file.write(datetime.datetime.now().strftime("Uploaded %Y-%m-%d %H:%M \n"))
    try:
        format_metadata(
            bibfile,
            upload_pdf=True,
            verbose=False,
            print_authors=False,
            production_zenodo=production,
            add_title=include_title,
            publication_date=publication_date,
            conference_dates=conference_dates
        )
    except UploadError as e:
        raise click.ClickException(
            f"{e}\nStopped. Entries already in {doi_filename(production)} are skipped when you re-run."
        )


@click.command()
@click.argument('bibfile', type=click.Path(exists=True))
@conference_options
@click.option('--authors', is_flag=True)
def check(bibfile, publication_date, conference_dates, authors):
    """Process metadata from a .bibtex file and print out to check it."""
    publication_date = publication_date.strftime('%Y-%m-%d')
    if authors:
        format_metadata(
            bibfile,
            upload_pdf=False,
            verbose=False,
            print_authors=True,
            production_zenodo=False,
            add_title=False,
            publication_date=publication_date,
            conference_dates=conference_dates
        )
    else:
        format_metadata(
            bibfile,
            upload_pdf=False,
            verbose=True,
            print_authors=False,
            production_zenodo=False,
            add_title=False,
            publication_date=publication_date,
            conference_dates=conference_dates
        )


@click.group()
def cli():
    pass


if __name__ == '__main__':
    cli.add_command(upload)
    cli.add_command(check)
    cli()
