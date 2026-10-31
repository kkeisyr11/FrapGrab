"""Inspect the actual public application bundle without copying private profiles."""
import json
import marshal
import sys
import types
import re
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader


def strings(code):
    for value in code.co_consts:
        if isinstance(value,str):yield value
        elif isinstance(value,types.CodeType):yield from strings(value)
        elif isinstance(value,tuple):
            for item in value:
                if isinstance(item,str):yield item


def contains_private(text,private_terms,public_repositories=()):
    text=text.casefold()
    for repo in public_repositories:
        # A public release repository can share the publisher's gamer nickname.
        # Exempt only its complete namespace, never the bare account/player name.
        text=re.sub(r'(?<![\w.-])'+re.escape(repo.casefold())+r'(?=$|[/\s\"\'<>#?.,:)])','',text)
    return any(term.casefold() in text for term in private_terms if term)


def audit_bundle(folder,private_terms=(),private_template=None,public_repositories=()):
    folder=Path(folder)
    archive=CArchiveReader(folder/"FrapGrab.exe")
    modules=archive.open_embedded_archive("PYZ.pyz")
    issues=[];checked=0
    for name in modules.toc:
        if name in ("core","gui") or name.startswith(("core.","gui.")):
            code=modules.extract(name)
            if not isinstance(code,types.CodeType):continue
            checked+=1
            if any(contains_private(text,private_terms,public_repositories) for text in strings(code)):
                issues.append("private text in module: "+name)
    if any(contains_private(text,private_terms,public_repositories) for text in strings(marshal.loads(archive.extract("main")))):
        issues.append("private text in main")
    template_bytes=Path(private_template).read_bytes() if private_template and Path(private_template).is_file() else None
    for path in folder.rglob("*"):
        if not path.is_file():continue
        relative=path.relative_to(folder)
        if path.name=="pixel-profile.json" or (path.name=="config.json" and (len(relative.parts)<=2 or "assets" in relative.parts or "core" in relative.parts)):
            issues.append("user configuration included: "+str(relative))
        if path.suffix.lower() in (".json",".md",".txt",".ini",".yaml",".yml"):
            content=path.read_text(encoding="utf-8",errors="replace").casefold()
            if contains_private(content,private_terms,public_repositories):issues.append("private text in file: "+str(relative))
        if template_bytes is not None and path.suffix.lower()==".png" and path.stat().st_size==len(template_bytes) and path.read_bytes()==template_bytes:
            issues.append("private HUD template included: "+str(relative))
    report={"success":not issues,"application_modules_checked":checked,"issues":issues,
            "tests_packaged":any(name=="tests" or name.startswith("tests.") for name in modules.toc)}
    if report["tests_packaged"]:report["issues"].append("test fixtures included");report["success"]=False
    return report


if __name__=="__main__":
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from core.config import load_config,DEFAULT_REPOSITORY
    cfg=load_config();template=None
    try:template=json.loads(Path(cfg["pixel_profile"]).read_text(encoding="utf-8"))["template"]
    except (OSError,ValueError,KeyError):pass
    result=audit_bundle(sys.argv[1],[cfg["gamertag"]] if cfg["gamertag"] else [],template,[DEFAULT_REPOSITORY])
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["success"] else 1)
