"""The click commands, run with CliRunner from a temporary working directory
that holds an `upload/` folder, so the default paths are exercised."""

import shutil

import pytest
from click.testing import CliRunner

import nime_zenodo_upload.__main__ as zu

from conftest import BIB, PDFS, TOKEN, add_happy_path, calls_to

DATES = ['--publication-date', '2006-06-04', '--conference-dates', '4 June - 8 June, 2006']


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A cwd shaped like the project: upload/ with the PDFs and the .bib file."""
    upload = tmp_path / 'upload'
    upload.mkdir()
    for name in PDFS:
        (upload / name).write_bytes(b'%PDF-1.4 fake\n')
    (upload / 'test.bib').write_text(BIB, encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def runner():
    return CliRunner()


def test_check_prints_metadata(runner, workdir, no_token_env):
    result = runner.invoke(zu.cli, ['check', 'upload/test.bib', *DATES])
    assert result.exit_code == 0, result.output
    assert "'title': 'Test Installation'" in result.output
    assert "'publication_date': '2006-06-04'" in result.output
    assert "'conference_dates': '4 June - 8 June, 2006'" in result.output
    assert "'conference_session': 'Installations'" in result.output
    assert "'title': 'A Music Piece'" in result.output
    assert not (workdir / 'nime_dois_sandbox.txt').exists()


def test_check_authors_lists_names_only(runner, workdir, no_token_env):
    result = runner.invoke(zu.cli, ['check', 'upload/test.bib', *DATES, '--authors'])
    assert result.exit_code == 0, result.output
    assert "'von Schlippenbach, Alexander'" in result.output
    assert "'dj sniff'" in result.output
    assert 'publication_date' not in result.output


def test_check_works_without_a_token_or_secrets_file(runner, workdir, no_token_env):
    assert not (workdir / 'secrets.toml').exists()
    result = runner.invoke(zu.cli, ['check', 'upload/test.bib', *DATES])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize('command', ['check', 'upload'])
def test_conference_options_are_required(runner, workdir, command):
    result = runner.invoke(zu.cli, [command, 'upload/test.bib', '--publication-date', '2006-06-04'])
    assert result.exit_code == 2
    assert "Missing option '--conference-dates'" in result.output

    result = runner.invoke(zu.cli, [command, 'upload/test.bib', '--conference-dates', 'x'])
    assert result.exit_code == 2
    assert "Missing option '--publication-date'" in result.output


def test_publication_date_must_be_iso(runner, workdir):
    result = runner.invoke(zu.cli, ['check', 'upload/test.bib',
                                    '--publication-date', '2008-6', '--conference-dates', 'x'])
    assert result.exit_code == 2
    assert "Invalid value for '--publication-date'" in result.output
    assert '2008-6' in result.output


def test_missing_bibfile_is_rejected(runner, workdir):
    result = runner.invoke(zu.cli, ['check', 'upload/nope.bib', *DATES])
    assert result.exit_code == 2
    assert 'does not exist' in result.output


def test_upload_without_token_fails_before_prompt(runner, workdir, no_token_env):
    result = runner.invoke(zu.cli, ['upload', 'upload/test.bib', *DATES], input='\n')
    assert result.exit_code == 1
    assert 'No Zenodo token' in result.output
    assert 'ZENODO_SANDBOX_TOKEN' in result.output
    assert 'Press Enter' not in result.output
    assert not (workdir / 'nime_dois_sandbox.txt').exists()


def test_upload_reads_token_from_secrets_file(runner, workdir, no_token_env, zenodo):
    (workdir / 'secrets.toml').write_text(f"PUBLIC_TOKEN = 'pub'\nSANDBOX_TOKEN = '{TOKEN}'\n")
    add_happy_path(zenodo)
    shutil.rmtree(workdir / 'upload')
    (workdir / 'upload').mkdir()
    (workdir / 'upload' / 'nime2006_music_Adachi.pdf').write_bytes(b'%PDF')
    (workdir / 'upload' / 'one.bib').write_text(
        '@inproceedings{a, author={Adachi, Tomomi}, title={A Music Piece},'
        ' url={https://www.nime.org/proceedings/2006/nime2006_music_Adachi.pdf}}')

    result = runner.invoke(zu.cli, ['upload', 'upload/one.bib', *DATES], input='\n')

    assert result.exit_code == 0, result.output
    assert f'access_token={TOKEN}' in zenodo.calls[0].request.url
    lines = (workdir / 'nime_dois_sandbox.txt').read_text().splitlines()
    assert lines[0].startswith('Uploaded ')
    assert lines[1] == 'nime2006_music_Adachi.pdf,123,10.5072/zenodo.123'
    assert not (workdir / 'nime_dois.txt').exists()


def test_upload_sandbox_happy_path_via_cli(runner, workdir, monkeypatch, zenodo):
    monkeypatch.setenv('ZENODO_SANDBOX_TOKEN', TOKEN)
    add_happy_path(zenodo)
    # Both bib entries get the same fake deposition; that is fine for the flow.
    result = runner.invoke(zu.cli, ['upload', 'upload/test.bib', *DATES, '--title'], input='\n')

    assert result.exit_code == 0, result.output
    assert 'sandbox Zenodo server' in result.output
    assert 'Press Enter to continue' in result.output
    assert len(calls_to(zenodo, 'POST', '/api/deposit/depositions')) == 2
    lines = (workdir / 'nime_dois_sandbox.txt').read_text().splitlines()
    assert lines[0].startswith('Uploaded ')
    assert lines[1:] == [
        'nime2006_installations_Baalman.pdf,123,10.5072/zenodo.123,Test Installation',
        'nime2006_music_Adachi.pdf,123,10.5072/zenodo.123,A Music Piece',
    ]


def test_upload_production_flag_uses_production_server_and_file(runner, workdir, monkeypatch, zenodo):
    import responses
    monkeypatch.setenv('ZENODO_PUBLIC_TOKEN', 'prod-token')
    monkeypatch.delenv('ZENODO_SANDBOX_TOKEN', raising=False)
    prod = 'https://zenodo.org/api/deposit/depositions'
    zenodo.add(responses.GET, prod, json=[], status=200)
    zenodo.add(responses.POST, prod, status=400, json={'message': 'bad'})

    result = runner.invoke(zu.cli, ['upload', 'upload/test.bib', *DATES, '--production'], input='\n')

    assert result.exit_code == 1
    assert 'production Zenodo server' in result.output
    assert 'access_token=prod-token' in zenodo.calls[0].request.url
    assert 'Entries already in nime_dois.txt are skipped' in result.output
    lines = (workdir / 'nime_dois.txt').read_text().splitlines()
    assert len(lines) == 1 and lines[0].startswith('Uploaded ')


def test_upload_missing_pdf_makes_no_request(runner, workdir, monkeypatch, zenodo):
    monkeypatch.setenv('ZENODO_SANDBOX_TOKEN', TOKEN)
    (workdir / 'upload' / 'nime2006_music_Adachi.pdf').unlink()

    result = runner.invoke(zu.cli, ['upload', 'upload/test.bib', *DATES], input='\n')

    assert result.exit_code == 0, result.output
    assert 'do not exist in the upload folder' in result.output
    assert len(zenodo.calls) == 0
