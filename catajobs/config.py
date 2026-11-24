from __future__ import annotations

import glob
import os
from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config"
DADOS = RAIZ / "dados"
SAIDA = RAIZ / "saida"
LOGS = RAIZ / "logs"
PROMPTS = RAIZ / "prompts"
PERFIL_NAVEGADOR = DADOS / "navegador"
CURRICULO_BASE = DADOS / "curriculo_base.md"
DB_PATH = DADOS / "catajobs.db"

for _p in (DADOS, SAIDA, LOGS):
    _p.mkdir(parents=True, exist_ok=True)


@lru_cache
def busca() -> dict:
    return yaml.safe_load((CONFIG / "busca.yaml").read_text(encoding="utf-8"))


def segredo(nome: str) -> str | None:
    """Lê uma chave da variável de ambiente CATAJOBS_<NOME> ou de config/segredos.yaml (fora do git)."""
    valor = os.environ.get(f"CATAJOBS_{nome.upper()}")
    if valor:
        return valor
    arq = CONFIG / "segredos.yaml"
    if arq.exists():
        return (yaml.safe_load(arq.read_text(encoding="utf-8")) or {}).get(nome)
    return None


@lru_cache
def perfil() -> dict:
    return yaml.safe_load((CONFIG / "perfil.yaml").read_text(encoding="utf-8"))


def curriculo_base() -> str:
    if not CURRICULO_BASE.exists() or not CURRICULO_BASE.read_text(encoding="utf-8").strip():
        raise SystemExit(f"Currículo base não encontrado. Coloque o seu currículo em {CURRICULO_BASE}")
    return CURRICULO_BASE.read_text(encoding="utf-8")


def prompt(nome: str) -> str:
    return (PROMPTS / f"{nome}.md").read_text(encoding="utf-8")


def guia_de_voz() -> str:
    """Guia de voz para a carta: config/voz.md (gravado no onboarding) ou a skill my-writing-style do Claude Code."""
    local = CONFIG / "voz.md"
    if local.exists() and local.read_text(encoding="utf-8").strip():
        return local.read_text(encoding="utf-8").strip()
    base = Path(os.path.expanduser("~")) / ".claude" / "skills"
    achados = glob.glob(str(base / "**" / "my-writing-style" / "SKILL.md"), recursive=True)
    if achados:
        texto = Path(sorted(achados, key=os.path.getmtime)[-1]).read_text(encoding="utf-8")
        if texto.startswith("---"):
            texto = texto.split("---", 2)[-1]
        return texto.strip()
    return ""
