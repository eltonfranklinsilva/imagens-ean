#!/usr/bin/env python3
"""
sync_imagens_ean.py
-------------------
Sincroniza imagens de produtos (organizadas por EAN) de uma pasta local
para o repositório GitHub: eltonfranklinsilva/imagens-ean
 
Uso:
    python sync_imagens_ean.py
 
Configuração:
    Edite as variáveis na seção CONFIG abaixo antes de rodar.
"""
 
import os
import sys
import base64
import json
import time
import hashlib
from pathlib import Path
 
# ─────────────────────────────────────────────
# CONFIG — edite aqui antes de rodar
# ─────────────────────────────────────────────
 
# Pasta local onde ficam as subpastas dos EANs
# Exemplo Windows : r"C:\Users\Elton\imagens-ean"
# Exemplo macOS   : "/Users/elton/imagens-ean"
LOCAL_DIR = r"C:\caminho\para\sua\pasta\imagens-ean"
 
# Seu token de acesso pessoal do GitHub
# Crie em: https://github.com/settings/tokens  (permissão: repo)
GITHUB_TOKEN = "ghp_SEU_TOKEN_AQUI"
 
# Dono e nome do repositório (não precisa alterar)
REPO_OWNER = "eltonfranklinsilva"
REPO_NAME  = "imagens-ean"
BRANCH     = "main"
 
# Extensões de imagem aceitas
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
 
# Pausa entre chamadas à API para não exceder o rate limit (segundos)
API_DELAY = 0.3
 
# ─────────────────────────────────────────────
# FIM DA CONFIG
# ─────────────────────────────────────────────
 
try:
    import urllib.request
    import urllib.error
except ImportError:
    print("❌ Módulo urllib não encontrado (Python padrão). Verifique sua instalação.")
    sys.exit(1)
 
 
API_BASE = "https://api.github.com"
HEADERS  = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept":        "application/vnd.github.v3+json",
    "Content-Type":  "application/json",
    "User-Agent":    "sync-imagens-ean/1.0",
}
 
 
# ─── Utilitários de API ───────────────────────
 
def api_request(method: str, path: str, body: dict = None):
    """Faz uma requisição à API do GitHub e retorna (status, dict)."""
    url  = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        return e.code, json.loads(body_text) if body_text else {}
 
 
def get_file_sha(repo_path: str) -> str | None:
    """Retorna o SHA do arquivo no GitHub, ou None se não existir."""
    status, data = api_request("GET", f"/repos/{REPO_OWNER}/{REPO_NAME}/contents/{repo_path}?ref={BRANCH}")
    if status == 200:
        return data.get("sha")
    return None
 
 
def upload_file(local_path: Path, repo_path: str, sha: str | None = None) -> bool:
    """
    Faz upload (create ou update) de um arquivo para o GitHub.
    Retorna True em caso de sucesso.
    """
    content_b64 = base64.b64encode(local_path.read_bytes()).decode()
    action      = "Atualizando" if sha else "Enviando"
    print(f"  {action}: {repo_path}")
 
    body = {
        "message": f"{'update' if sha else 'add'}: {repo_path}",
        "content": content_b64,
        "branch":  BRANCH,
    }
    if sha:
        body["sha"] = sha
 
    status, resp = api_request("PUT", f"/repos/{REPO_OWNER}/{REPO_NAME}/contents/{repo_path}", body)
    time.sleep(API_DELAY)
 
    if status in (200, 201):
        return True
 
    print(f"  ⚠️  Falha ({status}): {resp.get('message', 'erro desconhecido')}")
    return False
 
 
def file_changed(local_path: Path, repo_sha: str) -> bool:
    """
    Verifica se o arquivo local é diferente do que está no GitHub.
    O GitHub usa SHA1 do conteúdo com prefixo "blob <tamanho>\0".
    """
    data    = local_path.read_bytes()
    header  = f"blob {len(data)}\0".encode()
    git_sha = hashlib.sha1(header + data).hexdigest()
    return git_sha != repo_sha
 
 
# ─── Lógica principal ─────────────────────────
 
def sync():
    local_root = Path(LOCAL_DIR)
 
    if not local_root.exists():
        print(f"❌ Pasta local não encontrada: {local_root}")
        sys.exit(1)
 
    if GITHUB_TOKEN == "ghp_SEU_TOKEN_AQUI":
        print("❌ Configure GITHUB_TOKEN no início do script antes de rodar.")
        sys.exit(1)
 
    print(f"📂 Pasta local   : {local_root}")
    print(f"🐙 Repositório   : {REPO_OWNER}/{REPO_NAME} (branch: {BRANCH})")
    print("─" * 55)
 
    enviados    = 0
    atualizados = 0
    ignorados   = 0
    erros       = 0
 
    # Itera por subpastas (cada uma = um EAN)
    ean_dirs = sorted([d for d in local_root.iterdir() if d.is_dir()])
 
    if not ean_dirs:
        print("⚠️  Nenhuma subpasta de EAN encontrada na pasta local.")
        return
 
    for ean_dir in ean_dirs:
        ean = ean_dir.name
        imagens = sorted([
            f for f in ean_dir.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        ])
 
        if not imagens:
            continue
 
        print(f"\n📦 EAN: {ean}  ({len(imagens)} imagem(ns))")
 
        for img in imagens:
            repo_path = f"{ean}/{img.name}"
            sha_remoto = get_file_sha(repo_path)
            time.sleep(API_DELAY)
 
            if sha_remoto is None:
                # Arquivo novo — envia
                ok = upload_file(img, repo_path, sha=None)
                if ok:
                    enviados += 1
                else:
                    erros += 1
 
            elif file_changed(img, sha_remoto):
                # Arquivo modificado — atualiza
                ok = upload_file(img, repo_path, sha=sha_remoto)
                if ok:
                    atualizados += 1
                else:
                    erros += 1
 
            else:
                # Idêntico — pula
                print(f"  ✓  Sem mudanças: {repo_path}")
                ignorados += 1
                time.sleep(API_DELAY)
 
    print("\n" + "─" * 55)
    print(f"✅ Concluído!")
    print(f"   Enviados     : {enviados}")
    print(f"   Atualizados  : {atualizados}")
    print(f"   Sem mudanças : {ignorados}")
    if erros:
        print(f"   Erros        : {erros}")
 
 
if __name__ == "__main__":
    sync()
