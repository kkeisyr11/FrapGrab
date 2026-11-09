"""GitHub Releases updates: stable versions, matching installer and SHA-256."""
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from packaging.version import Version,InvalidVersion
from .config import CONFIG_DIR
from .media import MediaCancelled

CURRENT_VERSION="2.3.0"

_NOTES_LANGUAGE = re.compile(r"^#{1,6}[ \t]+(Polski|English|PL|EN)[ \t]*\r?$", re.IGNORECASE | re.MULTILINE)


def release_notes_for_language(notes, language):
    """Use the requested release section, with a fallback for older releases."""
    headings = list(_NOTES_LANGUAGE.finditer(notes))
    if not headings:
        return notes.strip()
    sections = {}
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(notes)
        content = notes[heading.end():end].strip()
        if content:
            key = "pl" if heading.group(1).lower() in ("pl", "polski") else "en"
            sections.setdefault(key, content)
    return sections.get(language) or next(iter(sections.values()), "")


def repository_name(value):
    value=value.strip().removesuffix("/").removesuffix(".git")
    if value.startswith("https://github.com/"):value=value[len("https://github.com/"):]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",value) or any(p in (".","..") for p in value.split("/")):
        raise ValueError("Wpisz repozytorium GitHub w formacie właściciel/repozytorium.")
    return value


class AutoUpdater:
    def __init__(self,repository):self.repository=repository_name(repository)

    def _request(self,url):
        return urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":f"Frap Grab/{CURRENT_VERSION}",
            "Accept":"application/vnd.github+json"}),timeout=20)

    def release_info(self,data):
        if data.get("draft") or data.get("prerelease"):raise ValueError("To wydanie testowe.")
        try:remote=Version(str(data.get("tag_name","")).removeprefix("v"))
        except InvalidVersion as exc:raise ValueError("Nieprawidłowy numer wersji wydania.") from exc
        if remote.is_prerelease or remote.is_devrelease:raise ValueError("To wydanie testowe.")
        notes = data.get("body")
        info={"has_update":remote>Version(CURRENT_VERSION),"version":str(remote),"notes":notes[:10000] if isinstance(notes, str) else ""}
        if not info["has_update"]:return info
        expected=f"Frap_Grab_Setup_{remote}.exe"
        asset=next((a for a in data.get("assets",[]) if a.get("name")==expected and a.get("state","uploaded")=="uploaded"),None)
        if not asset:raise ValueError("Wydanie nie zawiera instalatora Windows.")
        url=asset.get("browser_download_url","");self._validate_url(url)
        digest=asset.get("digest","")
        if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}",digest or ""):
            raise ValueError("Instalator nie ma sumy SHA-256 w GitHub Releases.")
        size=asset.get("size",0)
        if not isinstance(size,int) or not 0<size<=1_000_000_000:raise ValueError("Nieprawidłowy rozmiar instalatora.")
        return {**info,"url":url,"name":expected,"sha256":digest[7:].lower(),"size":size}

    def _validate_url(self,url):
        parsed=urllib.parse.urlparse(url)
        if parsed.scheme!="https" or parsed.netloc!="github.com" or not parsed.path.startswith(f"/{self.repository}/releases/download/"):
            raise ValueError("Instalator musi pochodzić z wybranego repozytorium GitHub.")

    def check(self):
        try:
            with self._request(f"https://api.github.com/repos/{self.repository}/releases/latest") as response:
                return self.release_info(json.loads(response.read(2_000_000)))
        except urllib.error.HTTPError as exc:
            if exc.code==404:raise ValueError("Repozytorium nie ma publicznego wydania Releases.") from exc
            raise

    def download(self,info,progress=None,cancelled=None):
        self._validate_url(info["url"])
        if not re.fullmatch(r"Frap_Grab_Setup_[0-9.]+\.exe",info["name"]):raise ValueError("Nieprawidłowa nazwa instalatora.")
        folder=Path(CONFIG_DIR)/"updates";folder.mkdir(exist_ok=True)
        out=folder/info["name"];partial=out.with_suffix(".partial")
        digest=hashlib.sha256();count=0
        try:
            with self._request(info["url"]) as response,partial.open("wb") as target:
                while True:
                    if cancelled and cancelled():raise MediaCancelled("Anulowano pobieranie.")
                    chunk=response.read(256*1024)
                    if not chunk:break
                    count+=len(chunk)
                    if count>info["size"]:raise ValueError("Rozmiar pobranego pliku jest nieprawidłowy.")
                    target.write(chunk);digest.update(chunk)
                    if progress:progress(count/info["size"])
            if count!=info["size"] or digest.hexdigest()!=info["sha256"]:
                raise ValueError("Suma SHA-256 instalatora jest nieprawidłowa. Plik odrzucony.")
            os.replace(partial,out)
            return out
        finally:partial.unlink(missing_ok=True)
