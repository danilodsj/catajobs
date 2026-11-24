"""Onboarding interativo: monta um perfil novo pergunta a pergunta.

Cada resposta é salva na hora em config/perfil.yaml, config/busca.yaml, config/voz.md e dados/curriculo_base.md,
então dá para parar no meio (digite `sair` ou Ctrl+C) e continuar depois escolhendo "Revisar / completar".
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from .config import CONFIG, CURRICULO_BASE, DADOS, DB_PATH

PERFIL_ARQ = CONFIG / "perfil.yaml"
BUSCA_ARQ = CONFIG / "busca.yaml"
VOZ_ARQ = CONFIG / "voz.md"
BACKUPS = CONFIG / "backups"
VOLTAR = object()


class Sair(Exception):
    pass


# =================================================================== TERMINAL
if os.name == "nt":
    os.system("")  # liga as cores ANSI no console do Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass
_COR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(cod: str, s: str) -> str:
    return f"\033[{cod}m{s}\033[0m" if _COR else s


def negrito(s): return _c("1", s)
def fraco(s): return _c("2", s)
def verde(s): return _c("32", s)
def amarelo(s): return _c("33", s)
def vermelho(s): return _c("31", s)
def ciano(s): return _c("36", s)


def _entrada(rotulo: str = "  › ") -> str:
    try:
        return input(rotulo)
    except EOFError:
        raise Sair from None


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


# ================================================================ VALIDAÇÕES
UFS = {"AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
       "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
       "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
       "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
       "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
       "SE": "Sergipe", "TO": "Tocantins"}


def v_email(s: str) -> str:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s):
        raise ValueError("E-mail inválido. Ex.: nome@gmail.com")
    return s.lower()


def v_telefone(s: str) -> str:
    d = re.sub(r"\D", "", s)
    if s.strip().startswith("+") and not d.startswith("55"):
        return "+" + d  # número de fora do Brasil, mantém
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) == 11:
        return f"+55 {d[:2]} {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"+55 {d[:2]} {d[2:6]}-{d[6:]}"
    raise ValueError("Use DDD + número. Ex.: 21 98765-4321")


def v_linkedin(s: str) -> str:
    s = s.strip().rstrip("/")
    m = re.search(r"linkedin\.com/in/([^/?#\s]+)", s)
    perfil = m.group(1) if m else (s if re.fullmatch(r"[\w\-]+", s) else None)
    if not perfil:
        raise ValueError("Cole o link do perfil (linkedin.com/in/seu-nome) ou só o final dele.")
    return f"https://www.linkedin.com/in/{perfil}"


def v_url(s: str) -> str:
    s = s.strip()
    if " " in s or "." not in s:
        raise ValueError("Link inválido.")
    return s if re.match(r"https?://", s) else "https://" + s


def v_data(s: str) -> str:
    d = re.sub(r"\D", "", s)
    try:
        data = dt.datetime.strptime(d, "%d%m%Y")
    except ValueError:
        raise ValueError("Use DD/MM/AAAA. Ex.: 07/03/1992") from None
    idade = (dt.datetime.now() - data).days / 365.25
    if not 14 <= idade <= 90:
        raise ValueError("Data fora do esperado, confira o ano.")
    return data.strftime("%d/%m/%Y")


def v_cpf(s: str) -> str:
    d = re.sub(r"\D", "", s)
    if len(d) != 11:
        raise ValueError("CPF precisa ter 11 dígitos.")
    if d == d[0] * 11:
        raise ValueError("CPF inválido, confira os dígitos.")
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10 % 11) % 10 != int(d[n]):
            raise ValueError("CPF inválido, confira os dígitos.")
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def v_uf(s: str) -> str:
    s = s.strip()
    uf = s.upper() if s.upper() in UFS else next((k for k, v in UFS.items() if _sem_acento(v).lower() ==
                                                   _sem_acento(s).lower()), None)
    if not uf:
        raise ValueError("Use a sigla do estado. Ex.: RJ, SP, MG")
    return uf


def _numero(t: str) -> int:
    t = t.lower().strip()
    mil = "mil" in t or t.endswith("k")
    t = re.sub(r"[^\d.,]", "", t)
    if mil:
        valor = float(t.replace(",", ".") or 0) * 1000
    else:
        t = re.sub(r",\d{1,2}$", "", t)  # centavos
        valor = float(t.replace(".", "").replace(",", "") or 0)
    return int(round(valor))


def v_dinheiro(moeda: str) -> Callable[[str], str]:
    def f(s: str) -> str:
        partes = re.findall(r"\d[\d.,]*\s*(?:mil|k)?", s.lower())
        if not partes:
            raise ValueError(f"Informe um valor. Ex.: 12000, 12 mil ou {moeda} 12.000")
        nums = [_numero(p) for p in partes[:2]]
        if min(nums) < 100:
            raise ValueError("Valor muito baixo, informe o mensal. Ex.: 12 mil")
        fmt = [f"{moeda} {n:,}".replace(",", ".") for n in nums]
        return fmt[0] if len(fmt) == 1 else f"{fmt[0]} a {fmt[1]} por mês"
    return f


def v_inteiro(lo: int, hi: int) -> Callable[[str], int]:
    def f(s: str) -> int:
        if not re.fullmatch(r"\s*\d+\s*", str(s)) or not lo <= int(s) <= hi:
            raise ValueError(f"Número de {lo} a {hi}.")
        return int(s)
    return f


# ================================================================= PERGUNTAS
@dataclass
class P:
    chave: str                          # caminho no estado: perfil.x, perfil.respostas.x, busca.a.b, x.<auxiliar>
    texto: str
    rotulo: str = ""
    ajuda: str = ""
    tipo: str = "texto"                 # texto | escolha | simnao | lista | longo
    opcoes: list = field(default_factory=list)   # str ou (valor, rótulo)
    livre: bool = False                 # escolha que aceita texto livre
    validar: Callable | None = None
    obrigatoria: bool = False
    exemplo: str = ""
    sugestao: str = ""                  # campo lido do currículo pela IA
    quando: Callable[[dict], bool] | None = None
    mascarar: bool = False


NAO_INFORMAR = "Prefiro não informar"
IDIOMA = ["Não possui", "Básico", "Intermediário", "Avançado", "Fluente"]
ACEITE = [("qualquer", "Sim, em qualquer cidade"), ("cidades", "Sim, só em algumas cidades"), ("nao", "Não")]
NIVEIS = [("estagio", "Estágio / trainee"), ("junior", "Júnior"), ("pleno", "Pleno"),
          ("senior", "Sênior / especialista"), ("coordenacao", "Coordenação"), ("gerencia", "Gerência / head")]
PALAVRAS_NIVEL = {
    "estagio": ["estagio", "estágio", "estagiario", "estagiário", "trainee", "aprendiz"],
    "junior": ["junior", "júnior", "jr", "assistente", "auxiliar"],
    "pleno": ["pleno"],
}
TODAS_PALAVRAS_NIVEL = {w for ws in PALAVRAS_NIVEL.values() for w in ws}


def _pres_ou_hib_cidades(E):
    return "cidades" in (E["x"].get("presencial"), E["x"].get("hibrido"))


def _diversidade(chave, texto, rotulo, opcoes, exemplo=""):
    return P(f"perfil.respostas.{chave}", texto, rotulo, tipo="escolha", opcoes=[*opcoes, NAO_INFORMAR], livre=True,
             exemplo=exemplo, ajuda="Opcional. Só é usada quando o formulário pergunta. Pode responder "
                                    f"\"{NAO_INFORMAR}\".")


SECOES: list[tuple[str, str, list[P]]] = [
    ("dados", "Dados pessoais e contato", [
        P("perfil.nome_completo", "Qual é o seu nome completo?", "Nome", obrigatoria=True, sugestao="nome_completo",
          ajuda="Vai no topo do currículo e em todos os formulários."),
        P("perfil.email", "Qual e-mail os recrutadores devem usar?", "E-mail", obrigatoria=True, validar=v_email,
          sugestao="email", ajuda="Também é o e-mail usado se o robô puder criar conta em sites de vagas."),
        P("perfil.telefone", "Telefone com DDD (de preferência WhatsApp)", "Telefone", obrigatoria=True,
          validar=v_telefone, exemplo="21 98765-4321", sugestao="telefone"),
        P("perfil.linkedin", "Link do seu LinkedIn", "LinkedIn", validar=v_linkedin, sugestao="linkedin",
          exemplo="linkedin.com/in/seu-nome", ajuda="Quase todo formulário pede. `-` deixa em branco."),
        P("perfil.portfolio", "Portfólio, site ou GitHub (opcional)", "Portfólio", validar=v_url, sugestao="portfolio"),
        P("perfil.cidade", "Em que cidade você mora?", "Cidade", obrigatoria=True, sugestao="cidade",
          exemplo="São Paulo"),
        P("perfil.estado", "Estado (sigla)", "Estado", obrigatoria=True, validar=v_uf, sugestao="estado",
          exemplo="SP"),
        P("perfil.pais", "País", "País", obrigatoria=True),
        P("perfil.data_nascimento", "Data de nascimento (opcional)", "Nascimento", validar=v_data,
          exemplo="07/03/1992", ajuda="Alguns formulários exigem. Sem ela, essas vagas ficam como \"precisa de você\"."),
        P("perfil.cpf", "CPF (opcional)", "CPF", validar=v_cpf, mascarar=True,
          ajuda="A Gupy e alguns sites exigem. Fica só em config/perfil.yaml, que está fora do git."),
    ]),
    ("trabalho", "Modelo de trabalho e disponibilidade", [
        P("x.remoto", "Aceita vaga 100% remota?", "Remoto", tipo="simnao"),
        P("x.presencial", "Aceita vaga presencial?", "Presencial", tipo="escolha", opcoes=ACEITE),
        P("x.hibrido", "Aceita vaga híbrida?", "Híbrido", tipo="escolha", opcoes=ACEITE),
        P("busca.localizacao.cidades_presencial_hibrido", "Em quais cidades aceita híbrido/presencial? "
          "(separe por vírgula)", "Cidades aceitas", tipo="lista", obrigatoria=True, quando=_pres_ou_hib_cidades,
          exemplo="São Paulo, Campinas",
          ajuda="O nome precisa bater com o começo do local da vaga (ex.: \"São Paulo\", não \"SP capital\")."),
        P("perfil.respostas.disponibilidade_inicio", "Em quanto tempo pode começar?", "Início", tipo="escolha",
          opcoes=["Imediata", "15 dias", "30 dias", "45 dias", "60 dias"], livre=True),
        P("perfil.respostas.disponibilidade_mudanca", "Topa se mudar de cidade por uma vaga?", "Mudança",
          tipo="simnao"),
        P("perfil.respostas.disponibilidade_viagens", "Tem disponibilidade para viagens?", "Viagens", tipo="simnao"),
        P("perfil.respostas.autorizado_trabalhar_brasil", "Está autorizado(a) a trabalhar no Brasil?",
          "Autorizado(a) no Brasil", tipo="simnao"),
        P("perfil.respostas.precisa_visto", "Precisa de visto ou patrocínio para trabalhar?", "Precisa de visto",
          tipo="simnao"),
        P("perfil.respostas.possui_cnpj", "Tem CNPJ (para vagas PJ)?", "Tem CNPJ", tipo="simnao"),
        P("perfil.respostas.experiencia_lideranca_equipe", "Já fez gestão formal de pessoas?", "Liderança",
          tipo="escolha", opcoes=["Sim", "Não"], livre=True, sugestao="lideranca", exemplo="Sim, time de 4 pessoas",
          ajuda="Gestão formal: pessoas reportando a você. Liderar projeto não conta aqui."),
    ]),
    ("remuneracao", "Remuneração", [
        P("perfil.respostas.pretensao_salarial_clt", "Pretensão salarial mensal CLT (mínimo)", "Pretensão CLT",
          obrigatoria=True, validar=v_dinheiro("R$"), exemplo="12 mil",
          ajuda="Em campo de valor único o robô usa esse mínimo. Em faixa, escolhe a que contém o mínimo."),
        P("perfil.respostas.pretensao_salarial_pj", "Pretensão mensal PJ (mínimo, opcional)", "Pretensão PJ",
          validar=v_dinheiro("R$"), exemplo="15 mil"),
        P("perfil.respostas.pretensao_salarial_usd", "Pretensão em dólar para vagas internacionais (opcional)",
          "Pretensão USD", validar=v_dinheiro("US$"), exemplo="3500 a 4000"),
        P("perfil.respostas.salario_atual_base", "Salário base atual, mensal (opcional)", "Salário atual",
          validar=v_dinheiro("R$")),
        P("perfil.respostas.remuneracao_variavel_atual", "Remuneração variável atual (opcional)", "Variável",
          exemplo="PLR de 2 salários/ano, ou: Não possui"),
    ]),
    ("formacao", "Formação e idiomas", [
        P("perfil.respostas.escolaridade", "Escolaridade (nível, curso, instituição e ano)", "Escolaridade",
          obrigatoria=True, sugestao="escolaridade", exemplo="Superior completo (Administração, USP, 2019)"),
        P("perfil.respostas.ingles", "Nível de inglês", "Inglês", tipo="escolha", opcoes=IDIOMA, sugestao="ingles",
          obrigatoria=True),
        P("perfil.respostas.espanhol", "Nível de espanhol", "Espanhol", tipo="escolha", opcoes=IDIOMA,
          sugestao="espanhol", obrigatoria=True),
    ]),
    ("diversidade", "Diversidade (opcional)", [
        _diversidade("pcd", "Você é pessoa com deficiência (PcD)?", "PcD", ["Não", "Sim"],
                     exemplo="Sim, deficiência auditiva"),
        _diversidade("genero", "Gênero", "Gênero", ["Mulher", "Homem", "Não binário"]),
        _diversidade("identidade_de_genero", "Identidade de gênero", "Identidade", ["Cisgênero", "Transgênero"]),
        _diversidade("orientacao_sexual", "Orientação sexual", "Orientação",
                     ["Heterossexual", "Homossexual", "Bissexual"]),
        _diversidade("estado_civil", "Estado civil", "Estado civil",
                     ["Solteiro(a)", "Casado(a)", "União estável", "Divorciado(a)", "Viúvo(a)"]),
        _diversidade("raca_etnia", "Raça/cor (classificação do IBGE)", "Raça/cor",
                     ["Branca", "Preta", "Parda", "Amarela", "Indígena"]),
        P("perfil.respostas.como_soube_da_vaga", "Resposta padrão para \"como soube da vaga?\"", "Como soube",
          tipo="escolha", opcoes=["LinkedIn", "Gupy", "Indicação", "Site da empresa"], livre=True),
    ]),
    ("busca", "O que você procura", [
        P("busca.termos", "Quais cargos você quer buscar? (separe por vírgula)", "Cargos buscados", tipo="lista",
          obrigatoria=True, sugestao="cargos_alvo",
          exemplo="analista financeiro senior, coordenador financeiro, financial analyst",
          ajuda="Cada termo vira uma busca no LinkedIn, na Gupy e nos outros sites. 5 a 20 termos, com variações e "
                "versões em inglês."),
        P("busca.perfil_alvo.areas", "Em uma frase, que tipo de vaga é a sua cara?", "Áreas-alvo", obrigatoria=True,
          sugestao="areas", exemplo="finanças corporativas (FP&A, controladoria, planejamento financeiro)",
          ajuda="A IA usa essa frase para dar a nota de fit de cada vaga."),
        P("busca.filtros.areas_titulo", "Palavras que, no título, mostram que a vaga é da sua área "
          "(separe por vírgula)", "Palavras da área", tipo="lista", obrigatoria=True, sugestao="palavras_area",
          exemplo="financeiro, finance, fp&a, controladoria, controller, planejamento financeiro",
          ajuda="Vaga sem nenhuma delas no título é descartada antes da IA, sem custo. Na dúvida, inclua mais."),
        P("x.nivel", "Qual o nível mínimo das vagas?", "Nível mínimo", tipo="escolha", opcoes=NIVEIS,
          obrigatoria=True, sugestao="nivel",
          ajuda="Títulos com níveis abaixo desse são descartados direto (ex.: mínimo Sênior descarta júnior e pleno)."),
        P("x.nao_quero", "Que tipo de vaga você NÃO quer, mesmo sendo da área? (opcional)", "Não quero",
          exemplo="vendas, atendimento, cargos de engenharia de software"),
        P("x.excluir_extra", "Palavras no título que eliminam a vaga direto (opcional, separe por vírgula)",
          "Palavras excluídas", tipo="lista", exemplo="vendedor, sdr, motorista",
          ajuda="Os níveis abaixo do mínimo já entram sozinhos, não precisa repetir."),
        P("busca.perfil_alvo.trilhas", "Em que trilhas as vagas devem ser agrupadas? (2 a 4 rótulos curtos)",
          "Trilhas", tipo="lista", obrigatoria=True, sugestao="trilhas", exemplo="fpa, controladoria, tesouraria",
          ajuda="Rótulos do dashboard. Vaga que a IA não encaixar em nenhuma trilha é descartada."),
        P("busca.filtros.nota_minima_fit", "Nota mínima de fit (0 a 100) para se candidatar", "Nota mínima",
          validar=v_inteiro(0, 100), obrigatoria=True,
          ajuda="65 = área e nível batem, faltam requisitos secundários. 80+ = só vagas muito aderentes."),
        P("busca.limites.aplicacoes_por_dia", "Máximo de candidaturas por dia", "Candidaturas/dia",
          validar=v_inteiro(1, 200), obrigatoria=True),
        P("perfil.permitir_criar_conta", "O robô pode criar conta em sites de vagas (Workday, InHire...)?",
          "Cria contas", tipo="simnao",
          ajuda="Se sim, defina a senha na variável de ambiente CATAJOBS_SENHA_ATS (ela não fica em arquivo)."),
        P("x.voz", "Cole um texto seu (post, e-mail, mensagem) para as cartas saírem no seu tom (opcional)",
          "Exemplo de escrita", tipo="longo",
          ajuda="Vai para config/voz.md. Sem ele, a carta usa a skill my-writing-style do Claude Code, se existir."),
    ]),
]


# ==================================================================== ESTADO
def _get(E: dict, chave: str):
    d = E
    for k in chave.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _set(E: dict, chave: str, valor) -> None:
    ks = chave.split(".")
    d = E
    for k in ks[:-1]:
        d = d.setdefault(k, {})
    d[ks[-1]] = valor


def _vazio(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


PERFIL_VAZIO = {
    "nome_completo": "", "email": "", "telefone": "", "linkedin": "", "portfolio": "", "cidade": "", "estado": "",
    "pais": "Brasil", "data_nascimento": "", "cpf": "", "permitir_criar_conta": False,
    "respostas": {
        "pretensao_salarial_clt": "", "pretensao_salarial_pj": "", "pretensao_salarial_usd": "",
        "salario_atual_base": "", "remuneracao_variavel_atual": "", "experiencia_lideranca_equipe": "",
        "disponibilidade_inicio": "Imediata", "aceita_presencial": "", "aceita_hibrido": "", "aceita_remoto": "",
        "disponibilidade_mudanca": False, "disponibilidade_viagens": True, "ingles": "", "espanhol": "",
        "escolaridade": "", "pcd": "", "genero": "", "identidade_de_genero": "", "orientacao_sexual": "",
        "estado_civil": "", "raca_etnia": "", "como_soube_da_vaga": "LinkedIn", "possui_cnpj": False,
        "autorizado_trabalhar_brasil": True, "precisa_visto": False,
    },
}


def _ler_yaml(arq: Path) -> dict:
    return (yaml.safe_load(arq.read_text(encoding="utf-8")) or {}) if arq.exists() else {}


def _modo_aceite(txt: str, cidades: list) -> str | None:
    t = _sem_acento(str(txt or "")).lower()
    if not t:
        return None
    if t.startswith("nao"):
        return "nao"
    return "cidades" if cidades and "qualquer" not in t else "qualquer"


def _carregar(novo: bool) -> dict:
    from .filtros import AREA
    perfil = json.loads(json.dumps(PERFIL_VAZIO))
    if not novo:
        atual = _ler_yaml(PERFIL_ARQ)
        perfil.update({k: v for k, v in atual.items() if k != "respostas"})
        perfil["respostas"].update(atual.get("respostas") or {})
    busca = _ler_yaml(BUSCA_ARQ)
    excl = list(busca.get("filtros", {}).get("titulo_excluir") or [])
    loc = busca.setdefault("localizacao", {})
    r = perfil["respostas"]
    x: dict[str, Any] = {}
    if novo:
        busca["termos"] = []
        busca.setdefault("filtros", {})["areas_titulo"] = []
        busca["perfil_alvo"] = {}
        loc["cidades_presencial_hibrido"] = []
        x["excluir_extra"] = []
    else:
        cidades = loc.get("cidades_presencial_hibrido") or []
        x["remoto"] = loc.get("aceita_remoto", True)
        x["presencial"] = _modo_aceite(r.get("aceita_presencial"), cidades)
        x["hibrido"] = _modo_aceite(r.get("aceita_hibrido"), cidades)
        busca.setdefault("filtros", {}).setdefault("areas_titulo", list(AREA))
        x["excluir_extra"] = [w for w in excl if w not in TODAS_PALAVRAS_NIVEL]
        x["voz"] = VOZ_ARQ.read_text(encoding="utf-8").strip() if VOZ_ARQ.exists() else ""
        alvo = busca.get("perfil_alvo") or {}
        if not alvo:
            from .etapas import PERFIL_ALVO_PADRAO
            alvo = dict(PERFIL_ALVO_PADRAO)
        busca["perfil_alvo"] = alvo
    nivel = ("senior" if "pleno" in excl else "pleno" if "junior" in excl else "junior" if "estagio" in excl
             else None)
    if not novo:
        x["nivel"] = nivel or "estagio"
    E = {"perfil": perfil, "busca": busca, "x": x, "sug": {}, "novo": novo, "tocadas": set(),
         "orig": {"nivel": x.get("nivel"), "nao_quero": "", "termos": list(busca.get("termos") or []),
                  "areas": list(busca.get("filtros", {}).get("areas_titulo") or []),
                  "cidades": list(loc.get("cidades_presencial_hibrido") or []), "x": dict(x)}}
    return E


# ================================================================== DERIVADOS
def _juntar(itens: list[str]) -> str:
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " ou " + itens[-1]


def _derivar(E: dict) -> None:
    x, r, b = E["x"], E["perfil"]["respostas"], E["busca"]
    loc = b.setdefault("localizacao", {})
    cidades = loc.get("cidades_presencial_hibrido") or []
    if not _pres_ou_hib_cidades(E):
        cidades = loc["cidades_presencial_hibrido"] = []
    frase = {"qualquer": "Sim, em qualquer cidade",
             "cidades": f"Sim, somente em {_juntar(cidades)}" if cidades else "Sim",
             "nao": "Não"}
    mudou_cidades = cidades != E["orig"]["cidades"]
    for modo in ("presencial", "hibrido"):
        if x.get(modo) and (E["novo"] or mudou_cidades or x[modo] != E["orig"]["x"].get(modo)):
            r[f"aceita_{modo}"] = frase[x[modo]]
    if x.get("remoto") is not None:
        r["aceita_remoto"] = "Sim, de qualquer lugar" if x["remoto"] else "Não"
        loc["aceita_remoto"] = bool(x["remoto"])
    if x.get("presencial") and x.get("hibrido"):
        loc["aceita_presencial_hibrido"] = not (x["presencial"] == x["hibrido"] == "nao")

    filtros = b.setdefault("filtros", {})
    nivel = x.get("nivel")
    if nivel or E["novo"]:
        idx = [k for k, _ in NIVEIS].index(nivel) if nivel else 0
        abaixo = [k for k, _ in NIVEIS[:idx] if k in PALAVRAS_NIVEL]
        palavras = [w for k in abaixo for w in PALAVRAS_NIVEL[k]]
        filtros["titulo_excluir"] = list(dict.fromkeys([*(x.get("excluir_extra") or []), *palavras]))
    alvo = b.setdefault("perfil_alvo", {})
    if alvo.get("areas"):
        alvo["especialidade"] = alvo["areas"] if E["novo"] or not alvo.get("especialidade") else alvo["especialidade"]
    mudou_nivel = nivel and (E["novo"] or nivel != E["orig"]["nivel"] or x.get("nao_quero"))
    if mudou_nivel:
        idx = [k for k, _ in NIVEIS].index(nivel)
        aceitos = ", ".join(rot for _, rot in NIVEIS[idx:])
        alvo["nivel"] = f"{NIVEIS[idx][1]} para cima. Aceita: {aceitos}."
        rej = (f"níveis abaixo de {NIVEIS[idx][1].lower()} (mesmo que o título não diga, confira na descrição o "
               "nível e os anos de experiência pedidos), estágio, " if idx > 0 else "")
        rej += "vagas fora das áreas-alvo"
        if x.get("nao_quero"):
            rej += f", {x['nao_quero'].rstrip('.')}"
        alvo["rejeitar"] = rej + "."
        if E["novo"]:
            alvo["observacoes"] = ""
    fontes = b.setdefault("fontes", {})
    termos = b.get("termos") or []
    if termos and termos != E["orig"]["termos"]:
        fontes.setdefault("google_vagas", {})["consultas"] = _consultas_google(E, termos)
        if E["novo"]:
            fontes.setdefault("remotas_internacionais", {})["termos"] = termos[:15]
    areas = filtros.get("areas_titulo") or []
    if areas and areas != E["orig"]["areas"]:
        b["termos_amplos"] = areas[:15]  # varredura ampla da Gupy, Remotar e vagas.com
        fontes.setdefault("remotas_internacionais", {})["tags"] = [a for a in areas if " " not in a][:6]


def _consultas_google(E: dict, termos: list[str]) -> list[dict]:
    loc = E["busca"]["localizacao"]
    p = E["perfil"]
    local = None
    cidade = (loc.get("cidades_presencial_hibrido") or [p.get("cidade")] or [None])[0]
    if cidade and p.get("estado") in UFS and loc.get("aceita_presencial_hibrido", True):
        local = f"{_sem_acento(cidade)}, State of {_sem_acento(UFS[p['estado']])}, Brazil"
    out = []
    for t in termos[:20]:
        if loc.get("aceita_remoto", True):
            out.append({"q": t, "remoto": True})
        if local:
            out.append({"q": t, "local": local})
    return out[:20]


# ============================================================ GRAVAR ARQUIVOS
def _q(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return '""'
    return json.dumps(str(v), ensure_ascii=False)


def _escrever(arq: Path, texto: str) -> None:
    tmp = arq.with_suffix(arq.suffix + ".tmp")
    eol = "\r\n" if arq.exists() and b"\r\n" in arq.read_bytes() else "\n"  # mantém o fim de linha do arquivo
    tmp.write_text(texto, encoding="utf-8", newline=eol)
    os.replace(tmp, arq)


MODELO_PERFIL = """# Dados usados para preencher formulários de candidatura. Gerado e atualizado por `python -m catajobs onboarding`.
# Campos vazios ("") fazem o agente marcar a vaga como "precisa_humano" quando o formulário exigir o dado.

nome_completo: {nome_completo}
email: {email}
telefone: {telefone}
linkedin: {linkedin}
portfolio: {portfolio}           # site, GitHub, Behance etc. (opcional)
cidade: {cidade}
estado: {estado}
pais: {pais}
data_nascimento: {data_nascimento}     # DD/MM/AAAA (alguns formulários exigem)
cpf: {cpf}

# Criação de conta em sites de candidatura (Workday, InHire, Sólides etc.)
# false: o agente para e marca "precisa_humano" quando o site exigir cadastro.
# true: o agente cria a conta com o e-mail acima e a senha da variável de ambiente CATAJOBS_SENHA_ATS
#       (a senha não fica salva em arquivo). Sites que pedem código por e-mail continuam como "precisa_humano".
permitir_criar_conta: {permitir_criar_conta}

# Respostas padrão para perguntas frequentes de formulário
respostas:
  # Pretensão mensal. Em campo de valor único, use o mínimo. Em faixa, escolha a que contém o mínimo.
  pretensao_salarial_clt: {r_pretensao_salarial_clt}   # a partir de
  pretensao_salarial_pj: {r_pretensao_salarial_pj}    # no mínimo
  pretensao_salarial_usd: {r_pretensao_salarial_usd}
  salario_atual_base: {r_salario_atual_base}      # mensal
  remuneracao_variavel_atual: {r_remuneracao_variavel_atual}
  experiencia_lideranca_equipe: {r_experiencia_lideranca_equipe} # gestão formal de pessoas
  disponibilidade_inicio: {r_disponibilidade_inicio}
  aceita_presencial: {r_aceita_presencial}
  aceita_hibrido: {r_aceita_hibrido}
  aceita_remoto: {r_aceita_remoto}
  disponibilidade_mudanca: {r_disponibilidade_mudanca}
  disponibilidade_viagens: {r_disponibilidade_viagens}
  ingles: {r_ingles}                  # Não possui, Básico, Intermediário, Avançado, Fluente
  espanhol: {r_espanhol}
  escolaridade: {r_escolaridade}
  pcd: {r_pcd}
  genero: {r_genero}
  identidade_de_genero: {r_identidade_de_genero}
  orientacao_sexual: {r_orientacao_sexual}
  estado_civil: {r_estado_civil}
  raca_etnia: {r_raca_etnia}
  como_soube_da_vaga: {r_como_soube_da_vaga}
  possui_cnpj: {r_possui_cnpj}
  autorizado_trabalhar_brasil: {r_autorizado_trabalhar_brasil}
  precisa_visto: {r_precisa_visto}
"""


def _render_perfil(p: dict) -> str:
    r = p.get("respostas") or {}
    campos = {k: _q(v) for k, v in p.items() if k != "respostas"}
    campos.update({f"r_{k}": _q(v) for k, v in r.items()})
    usados = set(re.findall(r"\{(\w+)\}", MODELO_PERFIL))
    texto = MODELO_PERFIL.format(**{k: campos.get(k, '""') for k in usados})
    extras_r = {k: v for k, v in r.items() if f"r_{k}" not in usados}
    extras = {k: v for k, v in p.items() if k != "respostas" and k not in usados}
    if extras_r:
        texto += "  # outras respostas\n" + "".join(f"  {k}: {_q(v) if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False)}\n"
                                                    for k, v in extras_r.items())
    if extras:
        texto += "\n" + yaml.safe_dump(extras, allow_unicode=True, sort_keys=False)
    return texto


# --- busca.yaml: troca só as chaves gerenciadas, preservando o resto do arquivo e os comentários
# caminho em busca.yaml -> perguntas que alimentam esse valor (só grava o que foi respondido nesta sessão)
GERENCIADAS = {
    ("termos",): {"busca.termos"},
    ("localizacao", "cidades_presencial_hibrido"): {"busca.localizacao.cidades_presencial_hibrido", "x.presencial",
                                                    "x.hibrido"},
    ("localizacao", "aceita_remoto"): {"x.remoto"},
    ("localizacao", "aceita_presencial_hibrido"): {"x.presencial", "x.hibrido"},
    ("filtros", "nota_minima_fit"): {"busca.filtros.nota_minima_fit"},
    ("filtros", "titulo_excluir"): {"x.nivel", "x.excluir_extra"},
    ("filtros", "areas_titulo"): {"busca.filtros.areas_titulo"},
    ("limites", "aplicacoes_por_dia"): {"busca.limites.aplicacoes_por_dia"},
    ("perfil_alvo",): {"busca.perfil_alvo.areas", "busca.perfil_alvo.trilhas", "x.nivel", "x.nao_quero"},
    ("fontes", "google_vagas", "consultas"): {"busca.termos"},
    ("fontes", "remotas_internacionais", "termos"): {"busca.termos"},
    ("termos_amplos",): {"busca.filtros.areas_titulo"},
    ("fontes", "remotas_internacionais", "tags"): {"busca.filtros.areas_titulo"},
}


def _indent(linha: str) -> int:
    return len(linha) - len(linha.lstrip(" "))


def _fim_regiao(linhas: list[str], idx: int, ind: int) -> int:
    j = idx + 1
    while j < len(linhas) and not (linhas[j].strip() and _indent(linhas[j]) <= ind):
        j += 1
    while j > idx + 1 and not linhas[j - 1].strip():
        j -= 1
    return j


def _achar(linhas: list[str], caminho: tuple) -> tuple[int, int, int] | None:
    ini, fim, ind, idx = 0, len(linhas), 0, None
    for k in caminho:
        rx = re.compile(rf"^ {{{ind}}}{re.escape(k)}:(\s|$)")
        idx = next((i for i in range(ini, fim) if rx.match(linhas[i])), None)
        if idx is None:
            return None
        ini, fim = idx + 1, _fim_regiao(linhas, idx, ind)
        ind += 2
    return idx, ind - 2, fim


def _bloco(chave: str, valor, ind: int, inline: bool = False, comentario: str = "") -> list[str]:
    pad = " " * ind
    com = f"  {comentario}" if comentario else ""
    if isinstance(valor, dict):
        out = [f"{pad}{chave}:"]
        for k, v in valor.items():
            out += _bloco(k, v, ind + 2)
        return out
    if isinstance(valor, list):
        if not valor:
            return [f"{pad}{chave}: []{com}"]
        if inline and all(not isinstance(v, (dict, list)) for v in valor):
            return [f"{pad}{chave}: [{', '.join(_q(v) for v in valor)}]{com}"]
        out = [f"{pad}{chave}:"]
        for v in valor:
            if isinstance(v, dict):
                out.append(f"{pad}  - {{{', '.join(f'{k}: {_q(w)}' for k, w in v.items())}}}")
            else:
                out.append(f"{pad}  - {_q(v)}")
        return out
    return [f"{pad}{chave}: {_q(valor)}{com}"]


def _definir(texto: str, caminho: tuple, valor) -> str:
    linhas = texto.split("\n")
    achado = _achar(linhas, caminho)
    if achado:
        idx, ind, fim = achado
        m = re.search(r"\s(#.*)$", linhas[idx])
        comentario = m.group(1) if m and not isinstance(valor, dict) else ""
        inline = bool(re.match(rf"^ *{re.escape(caminho[-1])}:\s*\[", linhas[idx]))
        linhas[idx:fim] = _bloco(caminho[-1], valor, ind, inline, comentario)
        return "\n".join(linhas)
    # chave nova: cria dentro do pai mais fundo que já existe
    for n in range(len(caminho) - 1, -1, -1):
        pai = _achar(linhas, caminho[:n]) if n else None
        if n and not pai:
            continue
        aninhado = valor
        for k in reversed(caminho[n + 1:]):
            aninhado = {k: aninhado}
        if pai:
            _, ind, fim = pai
            linhas[fim:fim] = _bloco(caminho[n], aninhado, ind + 2)
        else:
            while linhas and not linhas[-1].strip():
                linhas.pop()
            linhas += ["", "# Perfil-alvo usado pela IA na nota de fit (preenchido pelo onboarding)."
                       if caminho[0] == "perfil_alvo" else "", *_bloco(caminho[0], aninhado, 0), ""]
        return "\n".join(linhas)
    return texto


def _salvar_busca(E: dict) -> None:
    texto = BUSCA_ARQ.read_text(encoding="utf-8")
    atual = yaml.safe_load(texto) or {}
    alvo = E["busca"]
    mudou = []
    for caminho, fontes in GERENCIADAS.items():
        if not fontes & E["tocadas"]:
            continue
        novo, velho = _get(alvo, ".".join(caminho)), _get(atual, ".".join(caminho))
        if novo is None or velho == novo:
            continue
        if caminho == ("filtros", "titulo_excluir") and isinstance(velho, list) and set(velho) == set(novo):
            continue
        if caminho == ("perfil_alvo",):
            novo = {k: v for k, v in novo.items() if not _vazio(v)}
            if not novo:
                continue
        texto = _definir(texto, caminho, novo)
        mudou.append((caminho, novo))
    if not mudou:
        return
    conferido = yaml.safe_load(texto)
    for caminho, novo in mudou:
        if _get(conferido, ".".join(caminho)) != novo:
            raise RuntimeError(f"não consegui gravar {'.'.join(caminho)} em busca.yaml com segurança")
    _escrever(BUSCA_ARQ, texto.rstrip("\n") + "\n")


def _salvar(E: dict) -> None:
    _derivar(E)
    _escrever(PERFIL_ARQ, _render_perfil(E["perfil"]))
    _salvar_busca(E)
    voz = E["x"].get("voz")
    if voz is not None and (voz or VOZ_ARQ.exists()):
        if voz:
            _escrever(VOZ_ARQ, "# Exemplo de escrita do candidato (tom e jeito de escrever para as cartas)\n\n" + voz + "\n")
        elif VOZ_ARQ.exists():
            VOZ_ARQ.unlink()


# ===================================================================== TELA
def _fmt(v, mascarar=False, opcoes=None) -> str:
    if isinstance(v, bool):
        return "Sim" if v else "Não"
    if isinstance(v, list):
        return ", ".join(map(str, v)) if len(v) <= 6 else ", ".join(map(str, v[:6])) + f" (+{len(v) - 6})"
    if opcoes:
        for o in opcoes:
            if isinstance(o, tuple) and o[0] == v:
                return o[1]
    s = str(v).replace("\n", " ")
    if mascarar and len(s) > 6:
        s = re.sub(r"\d", "•", s[:-5]) + s[-5:]
    return s if len(s) <= 70 else s[:67] + "..."


def _todas() -> list[P]:
    return [q for _, _, qs in SECOES for q in qs]


def _progresso(E: dict) -> tuple[int, int]:
    qs = [q for q in _todas() if not q.quando or q.quando(E)]
    feitos = sum(1 for q in qs if not _vazio(_get(E, q.chave)))
    return feitos, len(qs)


def _barra(E: dict) -> str:
    feitos, total = _progresso(E)
    n = round(20 * feitos / max(total, 1))
    return f"{verde('█' * n)}{fraco('░' * (20 - n))} {feitos}/{total}"


def _cabecalho(n: int, total: int, titulo: str, E: dict) -> None:
    print()
    print(ciano("━" * 64))
    print(f"  {negrito(f'Etapa {n}/{total} · {titulo}')}")
    print(f"  Perfil: {_barra(E)}")
    print(ciano("━" * 64))


def _ficha(E: dict, titulo: str, perguntas: list[P]) -> None:
    print(f"\n  {negrito('Ficha · ' + titulo)}")
    for q in perguntas:
        if q.quando and not q.quando(E):
            continue
        v = _get(E, q.chave)
        if _vazio(v):
            marca = vermelho("✗") if q.obrigatoria else fraco("·")
            print(f"   {marca} {q.rotulo:<24} {fraco('(vazio)')}")
        else:
            print(f"   {verde('✓')} {q.rotulo:<24} {_fmt(v, q.mascarar, q.opcoes)}")


def _ler_longo() -> str:
    print(fraco("    Cole o texto e termine com uma linha só com FIM (Enter direto, sem colar, pula)."))
    linhas = []
    while True:
        l = _entrada("    ")
        if l.strip().upper() == "FIM" or (not linhas and not l.strip()):
            break
        linhas.append(l)
    return "\n".join(linhas).strip()


def _perguntar(E: dict, q: P, i: int, n: int):
    atual = _get(E, q.chave)
    sug = E["sug"].get(q.sugestao) if q.sugestao else None
    padrao, de_sugestao = (atual, False) if not _vazio(atual) else (sug, not _vazio(sug))
    if isinstance(padrao, str) and q.tipo == "escolha" and not q.livre:
        validos = [o[0] if isinstance(o, tuple) else o for o in q.opcoes]
        if padrao not in validos:
            padrao, de_sugestao = None, False
    print(f"\n  {fraco(f'{i}/{n}')}  {negrito(q.texto)}")
    if q.exemplo:
        print(fraco(f"        ex.: {q.exemplo}"))
    if q.tipo == "escolha":
        for k, o in enumerate(q.opcoes, 1):
            valor, rot = o if isinstance(o, tuple) else (o, o)
            marca = verde("•") if valor == padrao else " "
            print(f"      {marca} {k}) {rot}")
        if q.livre:
            print(fraco("        (ou escreva a sua resposta)"))
    while True:
        dica = []
        if not _vazio(padrao) or isinstance(padrao, bool):
            origem = amarelo("sugestão do currículo") if de_sugestao else "atual"
            dica.append(f"Enter = {_fmt(padrao, q.mascarar, q.opcoes)} ({origem})")
        elif not q.obrigatoria and q.tipo != "simnao":
            dica.append("Enter pula")
        if q.tipo == "simnao":
            dica.insert(0, "s/n")
        dica.append("? ajuda · < voltar · sair")
        print(fraco("        " + " · ".join(dica)))
        if q.tipo == "longo":
            if _vazio(padrao):
                print(fraco("        `colar` para colar o texto"))
            else:
                print(fraco("        `trocar` cola outro texto · `-` apaga"))
            bruto = _entrada().strip()
            if bruto.lower() in ("colar", "trocar"):
                return _ler_longo() or padrao or ""
        else:
            bruto = _entrada().strip()
        if bruto == "?":
            print(ciano("        " + (q.ajuda or "Sem explicação extra para essa.")))
            continue
        if bruto == "<":
            return VOLTAR
        if bruto.lower() == "sair":
            raise Sair
        if bruto == "":
            if not _vazio(padrao) or isinstance(padrao, bool):
                return padrao
            if q.obrigatoria or q.tipo == "simnao":
                print(vermelho("        Essa é obrigatória."))
                continue
            return [] if q.tipo == "lista" else ""
        if bruto == "-":
            if q.obrigatoria or q.tipo == "simnao":
                print(vermelho("        Essa não pode ficar em branco."))
                continue
            return [] if q.tipo == "lista" else ""
        try:
            valor = _interpretar(q, bruto)
            if q.validar:
                valor = q.validar(valor)
            return valor
        except ValueError as e:
            print(vermelho(f"        {e}"))


def _interpretar(q: P, s: str):
    if q.tipo == "simnao":
        t = _sem_acento(s).lower()
        if t in ("s", "sim", "y", "yes", "1"):
            return True
        if t in ("n", "nao", "no", "0"):
            return False
        raise ValueError("Responda s ou n.")
    if q.tipo == "lista":
        return list(dict.fromkeys(x.strip() for x in re.split(r"[,;\n]", s) if x.strip()))
    if q.tipo == "escolha":
        ops = [o if isinstance(o, tuple) else (o, o) for o in q.opcoes]
        if s.isdigit() and 1 <= int(s) <= len(ops):
            return ops[int(s) - 1][0]
        t = _sem_acento(s).lower()
        for valor, rot in ops:
            if t in (_sem_acento(str(valor)).lower(), _sem_acento(rot).lower()):
                return valor
        if q.livre:
            return s
        raise ValueError(f"Escolha um número de 1 a {len(ops)}.")
    return s


def _rodar_secao(E: dict, n: int, total: int, titulo: str, perguntas: list[P]) -> None:
    _cabecalho(n, total, titulo, E)
    i = 0
    while True:
        ativas = [q for q in perguntas if not q.quando or q.quando(E)]
        if i >= len(ativas):
            break
        q = ativas[i]
        r = _perguntar(E, q, i + 1, len(ativas))
        if r is VOLTAR:
            i = max(0, i - 1)
            continue
        _set(E, q.chave, r)
        E["tocadas"].add(q.chave)
        _salvar(E)
        print(verde("        ✓ salvo"))
        i += 1
    _ficha(E, titulo, perguntas)


# ================================================================= CURRÍCULO
def _ler_arquivo(caminho: str) -> tuple[str, str]:
    c = caminho.strip().strip("&").strip().strip("'\"")
    arq = Path(os.path.expandvars(os.path.expanduser(c)))
    if not arq.exists():
        raise ValueError(f"Arquivo não encontrado: {arq}")
    ext = arq.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        texto = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(arq)).pages)
    elif ext == ".docx":
        import docx
        d = docx.Document(str(arq))
        texto = "\n".join(p.text for p in d.paragraphs)
        for t in d.tables:
            texto += "\n" + "\n".join(" | ".join(c.text for c in row.cells) for row in t.rows)
    elif ext in (".md", ".txt"):
        texto = arq.read_text(encoding="utf-8", errors="replace")
    else:
        raise ValueError("Formato não suportado. Use PDF, DOCX, TXT ou MD.")
    if len(texto.strip()) < 200:
        raise ValueError("Quase não saiu texto desse arquivo (PDF escaneado?). Tente o DOCX ou cole o texto.")
    return texto.strip(), ext


SCHEMA_EXTRACAO = {
    "type": "object",
    "properties": {
        **{k: {"type": "string"} for k in ("nome_completo", "email", "telefone", "linkedin", "portfolio", "cidade",
                                           "estado", "escolaridade", "ingles", "espanhol", "lideranca", "areas",
                                           "nivel", "curriculo_markdown")},
        **{k: {"type": "array", "items": {"type": "string"}} for k in ("cargos_alvo", "palavras_area", "trilhas")},
    },
    "required": ["nome_completo", "email", "telefone", "linkedin", "portfolio", "cidade", "estado", "escolaridade",
                 "ingles", "espanhol", "lideranca", "areas", "nivel", "cargos_alvo", "palavras_area", "trilhas",
                 "curriculo_markdown"],
}

PROMPT_EXTRACAO = """Leia o currículo abaixo e preencha os campos do schema para montar o perfil de busca de vagas do candidato.

Regras:
- Dados pessoais: use só o que está escrito. Campo sem informação = "" (string vazia). Não invente nada.
- estado: sigla da UF brasileira (ex.: "SP"), ou "" se não der para saber.
- escolaridade: nível + curso, instituição e ano. Ex.: "Superior completo (Administração, USP, 2019)".
- ingles e espanhol: exatamente um de "Não possui", "Básico", "Intermediário", "Avançado", "Fluente", ou "" se o currículo não diz.
- lideranca: "Sim" só se houve gestão formal de pessoas (time reportando a ele/ela); senão "Não".
- nivel: o nível de vaga que faz sentido buscar hoje, exatamente um de: estagio, junior, pleno, senior, coordenacao, gerencia.
- cargos_alvo: 8 a 15 termos de busca de vagas, em minúsculas, coerentes com a trajetória e o nível (inclua o nível no termo quando fizer sentido, ex.: "analista financeiro senior"), com 2 a 4 em inglês.
- areas: uma frase descrevendo as áreas e especialidades que o candidato deve buscar, com as sub-áreas entre parênteses.
- palavras_area: 12 a 30 palavras ou expressões curtas, minúsculas e sem acento, que no TÍTULO de uma vaga indicam a área do candidato (pt e en). Seja amplo.
- trilhas: 2 a 4 rótulos de uma palavra, minúsculos e sem acento, para agrupar as vagas (ex.: "marketing", "dados", "produto").
- curriculo_markdown: {instrucao_md}

<curriculo>
{curriculo}
</curriculo>
"""

INSTRUCAO_MD = ("o currículo inteiro reorganizado em Markdown: `# Nome`, linha com o título profissional, linha de "
                "contato, `## Resumo`, `## Resultados de destaque` (se houver), `## Competências`, "
                "`## Experiência Profissional` com `### Cargo, Empresa, Cidade | MM/AAAA a MM/AAAA` e bullets, "
                "`## Formação`, `## Idiomas` e outras seções que existirem. Mantenha TODO o conteúdo, números, datas e "
                "nomes, só reorganize e corrija quebras de linha do PDF. Não acrescente nada.")


def _sugerir_pela_ia(E: dict, texto: str, reorganizar: bool) -> None:
    from . import ia
    print(fraco("\n  Lendo o currículo com o Claude (leva de 30s a 2 min)..."))
    p = PROMPT_EXTRACAO.replace("{instrucao_md}", INSTRUCAO_MD if reorganizar else 'devolva "" (string vazia).')
    p = p.replace("{curriculo}", texto[:40000])
    try:
        r, _ = ia.rodar(p, SCHEMA_EXTRACAO, "sonnet", timeout_s=600, log_nome="onboarding_extracao")
    except Exception as e:  # noqa: BLE001
        print(amarelo(f"  Não deu para usar a IA agora ({str(e)[:160]}). Seguimos sem sugestões."))
        return
    for k, conv in (("telefone", v_telefone), ("linkedin", v_linkedin), ("email", v_email), ("estado", v_uf),
                    ("portfolio", v_url)):
        try:
            r[k] = conv(r[k]) if r.get(k) else ""
        except ValueError:
            r[k] = ""
    if r.get("nivel") not in dict(NIVEIS):
        r["nivel"] = ""
    E["sug"] = {k: v for k, v in r.items() if not _vazio(v)}
    md = (r.get("curriculo_markdown") or "").strip()
    if reorganizar and len(md) > 0.6 * len(texto):
        (DADOS / "curriculo_importado.txt").write_text(texto, encoding="utf-8")
        _escrever(CURRICULO_BASE, md + "\n")
        print(verde(f"  ✓ Currículo organizado em Markdown e salvo em {CURRICULO_BASE.relative_to(CONFIG.parent)}"))
        print(fraco("    (o texto original ficou em dados/curriculo_importado.txt)"))
    n = len([k for k in E["sug"] if k != "curriculo_markdown"])
    print(verde(f"  ✓ {n} respostas sugeridas a partir do currículo. Elas aparecem como "
                f"\"sugestão do currículo\": Enter aceita."))


def _etapa_curriculo(E: dict, n: int, total: int) -> None:
    _cabecalho(n, total, "Currículo", E)
    existe = CURRICULO_BASE.exists() and CURRICULO_BASE.read_text(encoding="utf-8").strip()
    print("\n  O currículo base é a única fonte de verdade: a IA nunca inventa nada fora dele.")
    print("  Quanto mais detalhe (resultados, números, ferramentas), melhores os currículos e cartas gerados.")
    if existe and not E["novo"]:
        print(fraco(f"  Atual: {CURRICULO_BASE.relative_to(CONFIG.parent)} "
                    f"({len(CURRICULO_BASE.read_text(encoding='utf-8'))} caracteres)"))
    print("\n      1) Importar um arquivo (PDF, DOCX, TXT ou MD)")
    print("      2) Colar o texto aqui")
    print(f"      3) {'Manter o atual' if existe and not E['novo'] else 'Pular por agora'}")
    while True:
        op = _entrada("  › ").strip().lower()
        if op == "sair":
            raise Sair
        if op in ("", "3"):
            if existe and not E["novo"]:
                if _sim("  Quer que a IA leia o currículo atual para sugerir respostas?", False):
                    _sugerir_pela_ia(E, CURRICULO_BASE.read_text(encoding="utf-8"), reorganizar=False)
            else:
                if E["novo"] and existe:
                    _escrever(CURRICULO_BASE, "")  # não deixa o currículo da pessoa anterior no perfil novo
                print(amarelo("  Sem currículo, o pipeline não roda. Rode o onboarding de novo depois para incluir."))
            return
        if op == "1":
            print(fraco("    Arraste o arquivo para cá ou cole o caminho completo."))
            try:
                texto, ext = _ler_arquivo(_entrada("    arquivo › "))
            except ValueError as e:
                print(vermelho(f"    {e}"))
                continue
            break
        if op == "2":
            texto, ext = _ler_longo(), ".txt"
            if len(texto) < 200:
                print(vermelho("    Texto curto demais para um currículo."))
                continue
            break
        print(vermelho("    Escolha 1, 2 ou 3."))
    _escrever(CURRICULO_BASE, texto + "\n")
    print(verde(f"  ✓ {len(texto)} caracteres salvos em {CURRICULO_BASE.relative_to(CONFIG.parent)}"))
    if _sim("  Quer que a IA leia o currículo, sugira as respostas e organize o texto?", True):
        _sugerir_pela_ia(E, texto, reorganizar=ext != ".md")


def _sim(pergunta: str, padrao: bool) -> bool:
    while True:
        r = _entrada(f"{pergunta} {fraco('[S/n]' if padrao else '[s/N]')} ").strip().lower()
        if r == "sair":
            raise Sair
        if r == "":
            return padrao
        if r in ("s", "sim", "n", "nao", "não"):
            return r.startswith("s")


# ================================================================ PRINCIPAL
def _backup() -> Path:
    destino = BACKUPS / dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    destino.mkdir(parents=True, exist_ok=True)
    for arq in (PERFIL_ARQ, BUSCA_ARQ, VOZ_ARQ, CURRICULO_BASE):
        if arq.exists():
            shutil.copy2(arq, destino / arq.name)
    return destino


def _resumo_final(E: dict, destino_backup: Path | None) -> None:
    print("\n" + ciano("━" * 64))
    print(f"  {negrito('Perfil pronto')}  {_barra(E)}")
    print(ciano("━" * 64))
    for _, titulo, qs in SECOES:
        _ficha(E, titulo, qs)
    pend = [q.rotulo for q in _todas() if q.obrigatoria and (not q.quando or q.quando(E)) and _vazio(_get(E, q.chave))]
    if not (CURRICULO_BASE.exists() and CURRICULO_BASE.read_text(encoding="utf-8").strip()):
        pend.insert(0, "Currículo")
    print()
    if pend:
        print(amarelo(f"  Faltam itens obrigatórios: {', '.join(pend)}. Rode o onboarding de novo e escolha "
                      "\"Revisar / completar\"."))
    print("  Arquivos atualizados: config/perfil.yaml, config/busca.yaml, dados/curriculo_base.md"
          + (", config/voz.md" if VOZ_ARQ.exists() else ""))
    if destino_backup:
        print(fraco(f"  Backup do perfil anterior: {destino_backup}"))
    print(f"\n  {negrito('Próximos passos')}")
    if E["novo"]:
        print("   1. python -m catajobs login        entre no LinkedIn, Gupy e Google com as contas da nova pessoa")
    print(f"   {'2' if E['novo'] else '1'}. python -m catajobs retriar      reaplica o filtro com a nova busca")
    print(f"   {'3' if E['novo'] else '2'}. python -m catajobs aplicar --simular --limite 3   confere o robô sem enviar")
    print()


def main() -> None:
    print("\n" + ciano("━" * 64))
    print(f"  {negrito('Catajobs · Onboarding de perfil')}")
    print(ciano("━" * 64))
    print("  Vou fazer as perguntas para montar o perfil. Cada resposta é salva na hora:")
    print("  dá para parar com `sair` e continuar depois. Em qualquer pergunta: `?` explica, `<` volta.")

    tem_perfil = PERFIL_ARQ.exists() and (_ler_yaml(PERFIL_ARQ).get("nome_completo") or "").strip()
    novo, destino = True, None
    if tem_perfil:
        nome = _ler_yaml(PERFIL_ARQ)["nome_completo"]
        print(f"\n  Já existe um perfil: {negrito(nome)}")
        print("      1) Revisar / completar esse perfil")
        print("      2) Criar um perfil novo do zero (o atual vai para config/backups/)")
        while True:
            op = _entrada("  › ").strip()
            if op in ("1", "2", "sair"):
                break
        if op == "sair":
            return
        novo = op == "2"
    if novo and tem_perfil:
        destino = _backup()
        print(verde(f"  ✓ Backup do perfil atual em {destino}"))
        if DB_PATH.exists() and _sim("  Arquivar também o histórico de vagas (o banco começa vazio para o perfil novo)?",
                                     True):
            try:
                shutil.move(str(DB_PATH), str(destino / DB_PATH.name))
                print(verde("  ✓ Histórico de vagas arquivado no backup."))
            except OSError as e:
                print(amarelo(f"  Não consegui mover o banco ({e}). Feche o dashboard/pipeline e mova à mão."))
        if VOZ_ARQ.exists():
            VOZ_ARQ.unlink()  # já está no backup
    E = _carregar(novo)

    etapas = [("curriculo", "Currículo", None), *SECOES]
    escolhidas = list(range(len(etapas)))
    if not novo:
        print("\n  Etapas:")
        for k, (_, titulo, *_r) in enumerate(etapas, 1):
            print(f"      {k}) {titulo}")
        r = _entrada(fraco("  Enter = todas, ou os números separados por vírgula › ")).strip()
        if r.lower() == "sair":
            return
        if r:
            escolhidas = sorted({int(x) - 1 for x in re.findall(r"\d+", r) if 1 <= int(x) <= len(etapas)})

    try:
        _salvar(E)
        for pos, k in enumerate(escolhidas, 1):
            chave, titulo, qs = etapas[k]
            if chave == "curriculo":
                _etapa_curriculo(E, pos, len(escolhidas))
            else:
                if chave == "diversidade" and not _sim("\n  Muitos formulários pedem dados de diversidade. "
                                                       "Quer responder agora?", True):
                    for q in qs[:-1]:
                        if _vazio(_get(E, q.chave)):
                            _set(E, q.chave, NAO_INFORMAR)
                    _salvar(E)
                    print(fraco(f"  Marcado como \"{NAO_INFORMAR}\" onde estava vazio."))
                    continue
                _rodar_secao(E, pos, len(escolhidas), titulo, qs)
    except (Sair, KeyboardInterrupt):
        print(amarelo("\n\n  Parado. Tudo que você respondeu já está salvo. Para continuar: "
                      "python -m catajobs onboarding → Revisar / completar."))
        return
    _resumo_final(E, destino)
