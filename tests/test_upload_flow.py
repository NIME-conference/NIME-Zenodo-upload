"""The upload flow against a fake Zenodo (the `responses` library): what gets
sent, what ends up in the DOI file, and how each failure is reported."""

import pytest
import requests
import responses

import nime_zenodo_upload.__main__ as zu

from conftest import DEPOSITIONS, TOKEN, add_happy_path, calls_to


def run_upload(bibfile, upload_folder, doi_file, **kwargs):
    kwargs.setdefault('publication_date', '2006-06-04')
    kwargs.setdefault('conference_dates', '4 June - 8 June, 2006')
    return zu.format_metadata(
        str(bibfile),
        upload_pdf=True,
        production_zenodo=False,
        upload_folder=str(upload_folder),
        doi_file=str(doi_file),
        **kwargs,
    )


@pytest.fixture
def sandbox_token(monkeypatch):
    monkeypatch.setenv('ZENODO_SANDBOX_TOKEN', TOKEN)
    monkeypatch.delenv('ZENODO_PUBLIC_TOKEN', raising=False)


def test_happy_path_single_entry(zenodo, sandbox_token, bibdata, upload_folder, doi_file):
    add_happy_path(zenodo)
    data = zu.entry_to_metadata(bibdata.entries['NIME06_Music'], '2006-06-04', 'dates')

    zu.upload_to_zenodo(data, 'nime2006_music_Adachi.pdf', upload_folder=str(upload_folder),
                        doi_file=str(doi_file))

    create = calls_to(zenodo, 'POST', '/api/deposit/depositions')
    assert len(create) == 1
    assert f'access_token={TOKEN}' in create[0].request.url
    assert create[0].request.headers['Content-Type'] == 'application/json'
    assert b'"title": "A Music Piece"' in create[0].request.body

    files = calls_to(zenodo, 'POST', '/files')
    assert len(files) == 1
    assert b'nime2006_music_Adachi.pdf' in files[0].request.body
    assert b'%PDF-1.4 fake' in files[0].request.body

    assert len(calls_to(zenodo, 'POST', '/actions/publish')) == 1
    assert doi_file.read_text() == 'nime2006_music_Adachi.pdf,123,10.5072/zenodo.123\n'


def test_happy_path_with_title(zenodo, sandbox_token, bibdata, upload_folder, doi_file):
    add_happy_path(zenodo)
    data = zu.entry_to_metadata(bibdata.entries['NIME06_Music'], '2006-06-04', 'dates')
    zu.upload_to_zenodo(data, 'nime2006_music_Adachi.pdf', add_title=True,
                        upload_folder=str(upload_folder), doi_file=str(doi_file))
    assert doi_file.read_text() == 'nime2006_music_Adachi.pdf,123,10.5072/zenodo.123,A Music Piece\n'


def test_explicit_token_is_used_without_env_or_secrets(zenodo, no_token_env, bibdata, upload_folder,
                                                      doi_file):
    add_happy_path(zenodo)
    data = zu.entry_to_metadata(bibdata.entries['NIME06_Music'], '2006-06-04', 'dates')
    zu.upload_to_zenodo(data, 'nime2006_music_Adachi.pdf', token='explicit-token',
                        upload_folder=str(upload_folder), doi_file=str(doi_file))
    assert 'access_token=explicit-token' in zenodo.calls[0].request.url


def test_format_metadata_uploads_each_entry_and_skips_recorded(
        zenodo, sandbox_token, bibfile, upload_folder, doi_file):
    doi_file.write_text('Uploaded 2026-10-16 12:06 \n'
                        'nime2006_installations_Baalman.pdf,99,10.5072/zenodo.99\n')
    add_happy_path(zenodo)

    run_upload(bibfile, upload_folder, doi_file)

    # Only the Adachi entry was uploaded; Baalman was already in the DOI file.
    create = calls_to(zenodo, 'POST', '/api/deposit/depositions')
    assert len(create) == 1
    assert b'"title": "A Music Piece"' in create[0].request.body
    assert doi_file.read_text().splitlines()[-1] == 'nime2006_music_Adachi.pdf,123,10.5072/zenodo.123'


def test_missing_pdf_aborts_before_any_request(zenodo, sandbox_token, bibfile, upload_folder, doi_file,
                                               capsys):
    (upload_folder / 'nime2006_music_Adachi.pdf').unlink()

    run_upload(bibfile, upload_folder, doi_file)

    assert len(zenodo.calls) == 0
    assert not doi_file.exists()
    out = capsys.readouterr().out
    assert 'nime2006_music_Adachi.pdf' in out
    assert 'do not exist in the upload folder' in out


def test_oversized_pdf_aborts_before_any_request(zenodo, sandbox_token, bibfile, upload_folder, doi_file,
                                                 monkeypatch, capsys):
    monkeypatch.setattr(zu, 'MAX_PDF_BYTES', 4)

    run_upload(bibfile, upload_folder, doi_file)

    assert len(zenodo.calls) == 0
    assert not doi_file.exists()
    assert 'larger than 100 MB' in capsys.readouterr().out


def test_400_on_create_aborts_with_no_doi_line(zenodo, sandbox_token, bibfile, upload_folder, doi_file):
    zenodo.add(responses.GET, DEPOSITIONS, json=[], status=200)
    zenodo.add(responses.POST, DEPOSITIONS, status=400,
               json={'status': 400, 'message': 'Validation error',
                     'errors': [{'field': 'metadata.related_identifiers.0.resource_type',
                                 'message': 'Invalid value journal-issn.'}]})

    with pytest.raises(zu.UploadError, match='Creating the deposition for nime2006_installations_Baalman.pdf failed'):
        run_upload(bibfile, upload_folder, doi_file)

    assert not doi_file.exists()
    assert calls_to(zenodo, 'POST', '/files') == []
    assert calls_to(zenodo, 'POST', '/actions/publish') == []


def test_dropped_connection_on_create_is_scrubbed(zenodo, sandbox_token, bibdata, upload_folder, doi_file):
    zenodo.add(responses.GET, DEPOSITIONS, json=[], status=200)
    zenodo.add(responses.POST, DEPOSITIONS, body=requests.ConnectionError(
        f"HTTPSConnectionPool(host='sandbox.zenodo.org', port=443): Max retries exceeded with url: "
        f"/api/deposit/depositions?access_token={TOKEN} (Caused by RemoteDisconnected)"))
    data = zu.entry_to_metadata(bibdata.entries['NIME06_Music'], '2006-06-04', 'dates')

    with pytest.raises(zu.UploadError) as excinfo:
        zu.upload_to_zenodo(data, 'nime2006_music_Adachi.pdf', upload_folder=str(upload_folder),
                            doi_file=str(doi_file))

    message = str(excinfo.value)
    assert TOKEN not in message
    assert 'access_token=***' in message
    assert 'me/uploads' in message
    assert not doi_file.exists()


def test_file_upload_failure_names_the_draft(zenodo, sandbox_token, bibdata, upload_folder, doi_file):
    zenodo.add(responses.GET, DEPOSITIONS, json=[], status=200)
    zenodo.add(responses.POST, DEPOSITIONS, json={'id': 123}, status=201)
    zenodo.add(responses.POST, f'{DEPOSITIONS}/123/files', body='<html>413</html>', status=413)
    data = zu.entry_to_metadata(bibdata.entries['NIME06_Music'], '2006-06-04', 'dates')

    with pytest.raises(zu.UploadError, match='to draft 123 failed'):
        zu.upload_to_zenodo(data, 'nime2006_music_Adachi.pdf', upload_folder=str(upload_folder),
                            doi_file=str(doi_file))
    assert calls_to(zenodo, 'POST', '/actions/publish') == []
    assert not doi_file.exists()


def test_504_on_publish_but_confirmed_published_records_doi(
        zenodo, sandbox_token, bibdata, upload_folder, doi_file, capsys):
    """Issue #5: a publish that times out has often gone through anyway."""
    add_happy_path(zenodo, publish_status=504)
    data = zu.entry_to_metadata(bibdata.entries['NIME06_Music'], '2006-06-04', 'dates')

    zu.upload_to_zenodo(data, 'nime2006_music_Adachi.pdf', upload_folder=str(upload_folder),
                        doi_file=str(doi_file))

    out = capsys.readouterr().out
    assert 'Error happened during publish: 504' in out
    assert 'was published anyway' in out
    assert doi_file.read_text() == 'nime2006_music_Adachi.pdf,123,10.5072/zenodo.123\n'


def test_publish_failed_and_not_published_raises(zenodo, sandbox_token, bibdata, upload_folder, doi_file):
    zenodo.add(responses.GET, DEPOSITIONS, json=[], status=200)
    zenodo.add(responses.POST, DEPOSITIONS, json={'id': 123}, status=201)
    zenodo.add(responses.POST, f'{DEPOSITIONS}/123/files', json={}, status=201)
    zenodo.add(responses.POST, f'{DEPOSITIONS}/123/actions/publish', json={'message': 'nope'}, status=500)
    zenodo.add(responses.GET, f'{DEPOSITIONS}/123',
               json={'id': 123, 'submitted': False, 'state': 'unsubmitted'}, status=200)
    data = zu.entry_to_metadata(bibdata.entries['NIME06_Music'], '2006-06-04', 'dates')

    with pytest.raises(zu.UploadError, match='deposition 123.*unpublished draft'):
        zu.upload_to_zenodo(data, 'nime2006_music_Adachi.pdf', upload_folder=str(upload_folder),
                            doi_file=str(doi_file))
    assert not doi_file.exists()


def test_get_retries_on_5xx_then_gives_up(zenodo, sandbox_token):
    for _ in range(zu.RETRIES):
        zenodo.add(responses.GET, DEPOSITIONS, status=504)
    with pytest.raises(zu.UploadError, match=f'failed {zu.RETRIES} times'):
        zu._get_with_retries(DEPOSITIONS, TOKEN)
    assert len(zenodo.calls) == zu.RETRIES


def test_get_retries_on_connection_error_then_succeeds(zenodo, sandbox_token):
    zenodo.add(responses.GET, DEPOSITIONS, body=requests.ConnectionError('dropped'))
    zenodo.add(responses.GET, DEPOSITIONS, json=[], status=200)
    resp = zu._get_with_retries(DEPOSITIONS, TOKEN)
    assert resp.status_code == 200
    assert len(zenodo.calls) == 2


def test_supplementary_files_uploaded_and_oversized_marked(
        zenodo, sandbox_token, bibdata, upload_folder, doi_file, monkeypatch, capsys):
    monkeypatch.setattr(zu, 'MAX_SUPP_BYTES', 20)
    (upload_folder / 'nime2006_music_Adachi_file01.txt').write_bytes(b'small')
    (upload_folder / 'nime2006_music_Adachi_file02.mp4').write_bytes(b'x' * 21)
    # Another paper's PDF sharing a prefix must not be picked up.
    (upload_folder / 'nime2006_music_Adachi2.pdf').write_bytes(b'other')
    add_happy_path(zenodo)
    data = zu.entry_to_metadata(bibdata.entries['NIME06_Music'], '2006-06-04', 'dates')

    zu.upload_to_zenodo(data, 'nime2006_music_Adachi.pdf', upload_folder=str(upload_folder),
                        doi_file=str(doi_file))

    files = calls_to(zenodo, 'POST', '/files')
    sent = [c.request.body for c in files]
    assert len(sent) == 2
    assert any(b'nime2006_music_Adachi_file01.txt' in b for b in sent)
    assert not any(b'file02' in b for b in sent)
    assert not any(b'Adachi2' in b for b in sent)
    assert 'Skipping supplementary file nime2006_music_Adachi_file02.mp4' in capsys.readouterr().out
    assert doi_file.read_text() == (
        'nime2006_music_Adachi.pdf,123,10.5072/zenodo.123*nime2006_music_Adachi_file02.mp4\n'
    )


def test_rejected_supplementary_file_does_not_abort(
        zenodo, sandbox_token, bibdata, upload_folder, doi_file):
    (upload_folder / 'nime2006_music_Adachi_file01.mp4').write_bytes(b'video')
    zenodo.add(responses.GET, DEPOSITIONS, json=[], status=200)
    zenodo.add(responses.POST, DEPOSITIONS, json={'id': 123}, status=201)
    zenodo.add(responses.POST, f'{DEPOSITIONS}/123/files', json={}, status=201)   # the PDF
    zenodo.add(responses.POST, f'{DEPOSITIONS}/123/files', body='<html>413</html>', status=413)
    zenodo.add(responses.POST, f'{DEPOSITIONS}/123/actions/publish', json={}, status=202)
    zenodo.add(responses.GET, f'{DEPOSITIONS}/123',
               json={'id': 123, 'submitted': True, 'state': 'done', 'doi': '10.5072/zenodo.123'})
    data = zu.entry_to_metadata(bibdata.entries['NIME06_Music'], '2006-06-04', 'dates')

    zu.upload_to_zenodo(data, 'nime2006_music_Adachi.pdf', upload_folder=str(upload_folder),
                        doi_file=str(doi_file))

    assert doi_file.read_text() == (
        'nime2006_music_Adachi.pdf,123,10.5072/zenodo.123*nime2006_music_Adachi_file01.mp4\n'
    )
