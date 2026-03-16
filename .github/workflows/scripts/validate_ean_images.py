#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Validador de nomes de imagens por EAN.

Regras:
- Diretórios de primeiro nível com nome composto apenas por dígitos são tratados como EANs.
- Dentro de cada diretório EAN, arquivos de imagem devem seguir o padrão:
    {EAN}_{POS}.{EXT}
  onde:
    - {EAN} == nome do diretório
    - {POS} é um inteiro positivo (1, 2, 3, ...)
    - {EXT} ∈ {jpg, jpeg, png, webp, gif, bmp, tif, tiff, svg} (case-insensitive)

Saídas:
- report/VALIDATION_REPORT.md : relatório legível
- report/validation-report.csv: detalhamento (linha a linha)
- report/validation-report.json: estrutura JSON com achados

Uso:
    python scripts/validate_ean_images.py --root . --out-dir ./report --check-sequential
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"}

def is_ean_dir(name: str) -> bool:
    # Considera EANs como somente dígitos (ex.: EAN-13). Aceita quaisquer dígitos (8-14 etc.).
    return name.isdigit()

def suggest_fix(ean: str, filename: str):
    """
    Tenta sugerir um rename correto.
    - Se já houver um número no nome, usa-o como posição.
    - Caso contrário, retorna None (sem sugestão).
    """
    stem = Path(filename).stem
    ext = Path(filename).suffix
    # Busca algo que pareça ser a última parte numérica
    m = re.search(r"(\d+)$", stem)
    if m:
        pos = m.group(1).lstrip("0") or "0"
        if pos.isdigit() and int(pos) > 0:
            ext_lower = ext.lower() if ext else ""
            if ext_lower in ALLOWED_EXTS:
                return f"{ean}_{int(pos)}{ext_lower}"
            elif ext_lower:
                # extensão não permitida, mas sugere com .jpg
                return f"{ean}_{int(pos)}.jpg"
            else:
                return f"{ean}_{int(pos)}.jpg"
    return None

def validate_folder(ean_dir: Path, check_sequential: bool = False):
    ean = ean_dir.name
    issues = []
    positions = []
    details = []

    for entry in sorted(ean_dir.iterdir()):
        if entry.is_dir():
            # Se houver subpastas inesperadas, registra
            issues.append({
                "type": "unexpected_subdir",
                "filename": entry.name,
                "reason": "Subdiretório inesperado dentro do diretório do EAN."
            })
            continue

        if not entry.is_file():
            continue

        ext = entry.suffix.lower()
        if ext not in ALLOWED_EXTS:
            issues.append({
                "type": "invalid_extension",
                "filename": entry.name,
                "reason": f"Extensão não permitida: '{entry.suffix}'"
            })
            details.append({
                "filename": entry.name,
                "ok": False,
                "reason": "Extensão inválida"
            })
            continue

        stem = entry.stem  # sem extensão
        # Padrão: EAN_POS
        m = re.fullmatch(rf"{re.escape(ean)}_(\d+)", stem)
        if not m:
            # Nome não segue o padrão exato
            hint = suggest_fix(ean, entry.name)
            reason = "Nome não segue o padrão EAN_POS (ex.: 1234567890123_1)"
            if ean + "_" in stem:
                # Tem prefixo EAN_ mas pos inválida?
                reason = "Posição inválida ou não numérica após EAN_"
            issues.append({
                "type": "invalid_name",
                "filename": entry.name,
                "reason": reason,
                "suggested": hint
            })
            details.append({
                "filename": entry.name,
                "ok": False,
                "reason": reason,
                "suggested": hint
            })
            continue

        pos_str = m.group(1)
        try:
            pos = int(pos_str)
        except ValueError:
            issues.append({
                "type": "invalid_position",
                "filename": entry.name,
                "reason": f"Posição não é um inteiro: '{pos_str}'"
            })
            details.append({
                "filename": entry.name,
                "ok": False,
                "reason": "Posição não inteira"
            })
            continue

        if pos <= 0:
            issues.append({
                "type": "non_positive_position",
                "filename": entry.name,
                "reason": f"Posição deve ser >= 1: '{pos}'"
            })
            details.append({
                "filename": entry.name,
                "ok": False,
                "reason": "Posição <= 0"
            })
            continue

        # OK
        positions.append(pos)
        details.append({
            "filename": entry.name,
            "ok": True,
            "position": pos
        })

    duplicates = []
    missing = []
    if positions:
        counts = Counter(positions)
        duplicates = sorted([p for p, c in counts.items() if c > 1])
        if check_sequential:
            max_pos = max(positions)
            existing = set(positions)
            missing = [p for p in range(1, max_pos + 1) if p not in existing]

    if duplicates:
        issues.append({
            "type": "duplicate_positions",
            "filename": None,
            "reason": f"Posições duplicadas: {duplicates}"
        })
    if check_sequential and missing:
        issues.append({
            "type": "missing_positions",
            "filename": None,
            "reason": f"Faltam posições na sequência: {missing}"
        })

    return {
        "ean": ean,
        "total_files": len([d for d in details if "filename" in d]),
        "ok_files": len([d for d in details if d.get("ok")]),
        "bad_files": len([d for d in details if not d.get("ok")]),
        "positions": sorted(positions),
        "duplicates": duplicates,
        "missing": missing if check_sequential else [],
        "issues": issues,
        "details": details
    }

def write_reports(results, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = out_dir / "validation-report.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # CSV
    csv_path = out_dir / "validation-report.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        f.write("ean,filename,ok,reason,suggested,duplicates,missing\n")
        for res in results["folders"]:
            ean = res["ean"]
            dups = ";".join(map(str, res.get("duplicates", []))) if res.get("duplicates") else ""
            miss = ";".join(map(str, res.get("missing", []))) if res.get("missing") else ""
            for det in res["details"]:
                ok = det.get("ok")
                fn = det.get("filename", "")
                reason = det.get("reason", "")
                suggested = det.get("suggested", "")
                f.write(f"{ean},{fn},{ok},{reason},{suggested},{dups},{miss}\n")

    # Markdown legível
    md_path = out_dir / "VALIDATION_REPORT.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write("# Validação de nomes de imagens por EAN\n\n")
        f.write(f"- Pastas analisadas: **{results['summary']['folders_analyzed']}**\n")
        f.write(f"- Pastas OK: **{results['summary']['folders_ok']}**\n")
        f.write(f"- Pastas com problemas: **{results['summary']['folders_bad']}**\n\n")

        for res in results["folders"]:
            has_problem = (res["bad_files"] > 0) or bool(res.get("duplicates")) or bool(res.get("missing"))
            status = "✅ OK" if not has_problem else "❌ Problemas"
            f.write(f"## {res['ean']} — {status}\n")
            f.write(f"- Arquivos: {res['total_files']} | OK: {res['ok_files']} | Falhas: {res['bad_files']}\n")
            if res.get("duplicates"):
                f.write(f"- **Duplicidades**: {res['duplicates']}\n")
            if res.get("missing"):
                f.write(f"- **Lacunas na sequência**: {res['missing']}\n")
            if res["issues"]:
                f.write("- **Detalhes**:\n")
                for iss in res["issues"]:
                    fn = iss.get("filename")
                    suggested = iss.get("suggested")
                    line = f"  - {iss['type']}: {iss['reason']}"
                    if fn:
                        line += f" | arquivo: `{fn}`"
                    if suggested:
                        line += f" | sugestão: `{suggested}`"
                    f.write(line + "\n")
            f.write("\n")

def main():
    parser = argparse.ArgumentParser(description="Validador de nomes de imagens por EAN.")
    parser.add_argument("--root", default=".", help="Diretório raiz do repositório (onde ficam as pastas EAN).")
    parser.add_argument("--out-dir", default="./report", help="Diretório de saída para relatórios.")
    parser.add_argument("--check-sequential", action="store_true",
                        help="Verifica lacunas na sequência de posições (1..N).")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = Path(args.out_dir).resolve()

    if not root.exists():
        print(f"Root '{root}' não encontrado.", file=sys.stderr)
        sys.exit(2)

    folders = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and is_ean_dir(entry.name):
            folders.append(entry)

    results = {"folders": []}
    folders_ok = 0
    folders_bad = 0

    for ean_dir in folders:
        res = validate_folder(ean_dir, check_sequential=args.check_sequential)
        has_problem = (res["bad_files"] > 0) or bool(res.get("duplicates")) or bool(res.get("missing"))
        if has_problem:
            folders_bad += 1
        else:
            folders_ok += 1
        results["folders"].append(res)

    results["summary"] = {
        "folders_analyzed": len(folders),
        "folders_ok": folders_ok,
        "folders_bad": folders_bad
    }

    write_reports(results, out_dir)

    # Exit code: 0 se tudo ok; 1 se houve problemas (útil para pipelines)
    sys.exit(0 if folders_bad == 0 else 1)

if __name__ == "__main__":
    main()
