"""Triagem por regras: elimina o que claramente não serve antes de gastar IA."""
from __future__ import annotations

import re

from .db import normalizar

AREA = [
    "marketing", "mkt", "growth", "crm", "midia", "media", "performance", "digital", "dados", "data",
    "analytics", "bi", "business intelligence", "inteligencia de mercado", "inteligencia artificial",
    "inteligencia comercial", "ia", "ai", "machine learning", "ml", "llm", "genai", "generative", "insights",
    "seo", "sem", "martech", "ecommerce", "e commerce", "branding", "marca", "cro", "lifecycle", "retencao",
    "aquisicao", "acquisition", "retention", "analise de dados", "cientista de dados", "data science", "automacao",
]
NIVEL = [
    "senior", "sr", "especialista", "specialist", "expert", "lead", "lider", "coordenador", "coordenadora",
    "coordenacao", "coordinator", "gerente", "manager", "head", "diretor", "diretora", "director",
    "principal", "staff", "superintendente", "iii", "consultor", "consultora",
]
PRODUTO = ["product manager", "gerente de produto", "product owner", "pm", "gestor de produto", "gestora de produto",
           "product lead", "head de produto", "head of product", "coordenador de produto", "coordenadora de produto"]
ANALISTA = ["analista", "analyst", "cientista", "scientist"]
BRASIL = ["brasil", "brazil", "sao paulo", "rio de janeiro", "belo horizonte", "curitiba", "porto alegre",
          "florianopolis", "recife", "salvador", "brasilia", "campinas", "remote", "remoto", "latam", "latin america",
          "sp", "rj", "mg", "pr", "sc", "rs"]


def _tem(texto: str, termos: list[str]) -> str | None:
    for t in termos:
        if re.search(rf"\b{re.escape(t)}\b", texto):
            return t
    return None


def triar(vaga: dict, cfg: dict) -> tuple[bool, str]:
    """Retorna (passa, motivo)."""
    titulo = normalizar(vaga["titulo"])
    excluir = [normalizar(x) for x in cfg["filtros"]["titulo_excluir"]]
    if (x := _tem(titulo, excluir)):
        return False, f"título contém '{x}'"

    if vaga["fonte"] in ("greenhouse", "lever", "ashby") and not _tem(normalizar(vaga.get("local", "")), BRASIL):
        return False, "fora do Brasil"

    loc = cfg["localizacao"]
    areas = [normalizar(x) for x in cfg["filtros"].get("areas_titulo") or AREA]
    cidades = [normalizar(c) for c in loc.get("cidades_presencial_hibrido") or []]
    modelo = vaga.get("modelo_trabalho")
    texto_local = normalizar(f"{vaga['titulo']} {vaga.get('local', '')}")
    if not modelo:
        if re.search(r"\b(remot[oa]|remote|home office|anywhere)\b", texto_local):
            modelo = "remoto"
        elif re.search(r"\b(hibrido|hybrid)\b", texto_local):
            modelo = "hibrido"
    if modelo == "remoto" and not loc.get("aceita_remoto", True):
        return False, "remoto não aceito"
    if modelo in ("hibrido", "presencial") and not loc.get("aceita_presencial_hibrido", True):
        return False, f"{modelo} não aceito"
    local_norm = normalizar(vaga.get("local", ""))
    # modelo desconhecido: a IA confere na descrição (regra de local no prompt de avaliação)
    # a cidade tem que abrir o campo de local ("Rio de Janeiro, RJ"), para não aceitar "Petrópolis, Rio de Janeiro"
    if cidades and modelo in ("hibrido", "presencial") and not any(local_norm.startswith(c) for c in cidades):
        return False, f"{modelo} fora das cidades aceitas"

    area = _tem(titulo, areas)
    nivel = _tem(titulo, NIVEL)
    produto = _tem(titulo, PRODUTO)

    if produto:
        if area:
            return True, f"produto + área no título ({area})"
        desc = normalizar((vaga.get("descricao") or "")[:4000])
        area_desc = _tem(desc, areas if cfg["filtros"].get("areas_titulo") else
                         ["marketing", "growth", "dados", "data", "analytics", "inteligencia artificial",
                          "machine learning", "ia", "ai", "llm", "crm", "martech", "genai"])
        if area_desc:
            return True, f"produto com área na descrição ({area_desc})"
        return False, "produto sem relação com as áreas-alvo"

    if not area:
        return False, "título fora das áreas-alvo"
    if nivel:
        return True, f"nível '{nivel}' + área '{area}'"
    if _tem(titulo, ANALISTA):
        return True, "analista sem nível no título, IA confere senioridade"
    return True, f"área '{area}', nível a confirmar pela IA"
