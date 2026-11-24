"""Coletores de vagas. Cada função devolve uma lista de dicts no formato da tabela `vagas`."""
from __future__ import annotations

import html
import random
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})


def _get(url: str, tentativas: int = 3, **kw) -> requests.Response | None:
    for i in range(tentativas):
        try:
            r = S.get(url, timeout=25, **kw)
            if r.status_code == 429:
                time.sleep(10 * (i + 1))
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except requests.RequestException:
            time.sleep(3 * (i + 1))
    return None


def html_para_texto(h: str) -> str:
    if not h:
        return ""
    texto = BeautifulSoup(html.unescape(h), "html.parser").get_text("\n")
    return re.sub(r"\n\s*\n+", "\n", texto).strip()


# ---------------------------------------------------------------- Gupy
def gupy(termo: str, dias_max: int = 21) -> list[dict]:
    vagas, offset, limite = [], 0, 100
    corte = datetime.now(timezone.utc) - timedelta(days=dias_max)
    while True:
        r = _get(f"https://portal.gupy.io/api/job-search/jobs?jobName={quote(termo)}&limit={limite}&offset={offset}")
        if not r:
            break
        dados = r.json()
        for j in dados.get("data", []):
            pub = j.get("publishedDate")
            if pub and datetime.fromisoformat(pub.replace("Z", "+00:00")) < corte:
                continue
            local = ", ".join(x for x in (j.get("city"), j.get("state")) if x)
            vagas.append({
                "id": f"gupy:{j['id']}",
                "fonte": "gupy",
                "titulo": j.get("name", "").strip(),
                "empresa": j.get("careerPageName", "").strip(),
                "local": local or "Brasil",
                "modelo_trabalho": {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial"}.get(
                    j.get("workplaceType"), j.get("workplaceType")),
                "url": j.get("jobUrl"),
                "url_aplicacao": j.get("jobUrl"),
                "tipo_aplicacao": "gupy",
                "descricao": html_para_texto(j.get("description", "")),
                "publicada_em": pub,
            })
        total = dados.get("pagination", {}).get("total", 0)
        offset += limite
        if offset >= total or offset >= 500:
            break
        time.sleep(0.5)
    return vagas


# ---------------------------------------------------------------- LinkedIn (modo visitante)
def linkedin(termo: str, geo_id: str, janela_horas: int, paginas: int) -> list[dict]:
    global LINKEDIN_BLOQUEADO
    vagas, inicio = [], 0
    if LINKEDIN_BLOQUEADO:
        return vagas
    for _ in range(paginas):
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
               f"keywords={quote(termo)}&geoId={geo_id}&f_TPR=r{janela_horas * 3600}&start={inicio}")
        try:
            r = S.get(url, timeout=25)
        except requests.RequestException:
            break
        if r.status_code == 429:
            time.sleep(30)  # uma pausa e uma nova tentativa; se continuar limitado, para o LinkedIn nesta execução
            r = S.get(url, timeout=25)
            if r.status_code == 429:
                LINKEDIN_BLOQUEADO = True
                break
        if r.status_code != 200 or not r.text.strip():
            break
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("div.base-search-card")
        for c in cards:
            urn = c.get("data-entity-urn", "")
            jid = urn.rsplit(":", 1)[-1]
            if not jid.isdigit():
                continue
            titulo = c.select_one(".base-search-card__title")
            empresa = c.select_one(".base-search-card__subtitle")
            local = c.select_one(".job-search-card__location")
            data = c.select_one("time")
            vagas.append({
                "id": f"linkedin:{jid}",
                "fonte": "linkedin",
                "titulo": titulo.get_text(strip=True) if titulo else "",
                "empresa": empresa.get_text(strip=True) if empresa else "",
                "local": local.get_text(strip=True) if local else "",
                "modelo_trabalho": None,
                "url": f"https://www.linkedin.com/jobs/view/{jid}/",
                "url_aplicacao": None,
                "tipo_aplicacao": None,
                "descricao": None,
                "publicada_em": data.get("datetime") if data else None,
            })
        if not cards:
            break
        inicio += len(cards)
        time.sleep(random.uniform(1.5, 3.0))
    return vagas


LINKEDIN_BLOQUEADO = False  # vira True no primeiro HTTP 429; o resto fica para a próxima execução


def linkedin_detalhar(vaga: dict) -> dict:
    """Busca descrição, modelo de trabalho e destino da candidatura (externa ou candidatura simplificada)."""
    global LINKEDIN_BLOQUEADO
    if LINKEDIN_BLOQUEADO:
        return vaga
    jid = vaga["id"].split(":", 1)[1]
    try:
        r = S.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}", timeout=25)
    except requests.RequestException:
        return vaga
    time.sleep(random.uniform(2.0, 4.0))
    if r.status_code == 429:
        LINKEDIN_BLOQUEADO = True
        return vaga
    if r.status_code != 200:
        return vaga
    soup = BeautifulSoup(r.text, "html.parser")
    desc = soup.select_one(".show-more-less-html__markup")
    vaga["descricao"] = html_para_texto(str(desc)) if desc else ""
    criterios = " ".join(x.get_text(" ", strip=True) for x in soup.select(".description__job-criteria-item"))
    vaga["descricao"] += f"\n\n[Critérios LinkedIn] {criterios}" if criterios else ""
    texto = (vaga["titulo"] + " " + vaga["local"] + " " + (vaga["descricao"] or "")).lower()
    if "remot" in texto or "remote" in texto:
        vaga["modelo_trabalho"] = "remoto"
    elif "híbrid" in texto or "hibrid" in texto or "hybrid" in texto:
        vaga["modelo_trabalho"] = "hibrido"
    code = soup.select_one("code#applyUrl")
    destino = None
    if code:
        m = re.search(r'"(https?://[^"]+)"', code.decode_contents())
        if m:
            bruto = html.unescape(m.group(1))
            destino = parse_qs(urlparse(bruto).query).get("url", [bruto])[0]
            destino = unquote(destino)
    if destino:
        vaga["url_aplicacao"] = destino
        vaga["tipo_aplicacao"] = detectar_plataforma(destino)
    else:
        vaga["url_aplicacao"] = vaga["url"]
        vaga["tipo_aplicacao"] = "linkedin_simplificada"
    return vaga


def detectar_plataforma(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for chave, nome in (("gupy.io", "gupy"), ("greenhouse.io", "greenhouse"), ("lever.co", "lever"),
                        ("workday", "workday"), ("myworkdayjobs", "workday"), ("inhire", "inhire"),
                        ("solides", "solides"), ("kenoby", "kenoby"), ("abler", "abler"), ("vagas.com", "vagas.com"),
                        ("infojobs", "infojobs"), ("successfactors", "successfactors"), ("smartrecruiters", "smartrecruiters"),
                        ("recrutei", "recrutei"), ("pandape", "pandape"), ("bamboohr", "bamboohr"), ("ashbyhq", "ashby"),
                        ("teamtailor", "teamtailor"), ("taleo", "taleo"), ("linkedin.com", "linkedin_simplificada")):
        if chave in host:
            return nome
    return "outra"


# ---------------------------------------------------------------- Greenhouse
def greenhouse(token: str) -> list[dict]:
    r = _get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    if not r:
        return []
    vagas = []
    for j in r.json().get("jobs", []):
        vagas.append({
            "id": f"greenhouse:{token}:{j['id']}",
            "fonte": "greenhouse",
            "titulo": j.get("title", "").strip(),
            "empresa": token,
            "local": (j.get("location") or {}).get("name", ""),
            "modelo_trabalho": None,
            "url": j.get("absolute_url"),
            "url_aplicacao": j.get("absolute_url"),
            "tipo_aplicacao": "greenhouse",
            "descricao": html_para_texto(j.get("content", "")),
            "publicada_em": j.get("updated_at"),
        })
    return vagas


# ---------------------------------------------------------------- Lever
def lever(empresa: str) -> list[dict]:
    r = _get(f"https://api.lever.co/v0/postings/{empresa}?mode=json")
    if not r:
        return []
    vagas = []
    for j in r.json():
        listas = "\n".join(f"{l.get('text')}\n{html_para_texto(l.get('content', ''))}" for l in j.get("lists", []))
        criado = j.get("createdAt")
        vagas.append({
            "id": f"lever:{empresa}:{j['id']}",
            "fonte": "lever",
            "titulo": j.get("text", "").strip(),
            "empresa": empresa,
            "local": (j.get("categories") or {}).get("location", ""),
            "modelo_trabalho": {"remote": "remoto", "hybrid": "hibrido", "onsite": "presencial"}.get(j.get("workplaceType")),
            "url": j.get("hostedUrl"),
            "url_aplicacao": j.get("applyUrl") or j.get("hostedUrl"),
            "tipo_aplicacao": "lever",
            "descricao": (j.get("descriptionPlain") or "") + "\n" + listas,
            "publicada_em": datetime.fromtimestamp(criado / 1000, timezone.utc).isoformat() if criado else None,
        })
    return vagas


# ---------------------------------------------------------------- Ashby
def ashby(org: str) -> list[dict]:
    r = _get(f"https://api.ashbyhq.com/posting-api/job-board/{org}")
    if not r:
        return []
    vagas = []
    for j in r.json().get("jobs", []):
        if j.get("isListed") is False:
            continue
        locais = [j.get("location") or ""] + [(x or {}).get("location", "") for x in j.get("secondaryLocations") or []]
        pais = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or ""
        vagas.append({
            "id": f"ashby:{org}:{j['id']}",
            "fonte": "ashby",
            "titulo": (j.get("title") or "").strip(),
            "empresa": org,
            "local": ", ".join(x for x in locais + [pais] if x),
            "modelo_trabalho": {"Remote": "remoto", "Hybrid": "hibrido", "OnSite": "presencial"}.get(j.get("workplaceType")),
            "url": j.get("jobUrl"),
            "url_aplicacao": j.get("applyUrl") or j.get("jobUrl"),
            "tipo_aplicacao": "ashby",
            "descricao": j.get("descriptionPlain") or html_para_texto(j.get("descriptionHtml", "")),
            "publicada_em": j.get("publishedAt"),
        })
    return vagas


# ---------------------------------------------------------------- Remotar (vagas remotas e híbridas no Brasil)
def remotar(termo: str, dias_max: int = 21, paginas: int = 4) -> list[dict]:
    vagas = []
    corte = datetime.now(timezone.utc) - timedelta(days=dias_max)
    for pagina in range(1, paginas + 1):
        r = _get(f"https://api.remotar.com.br/jobs?search={quote(termo)}&page={pagina}")
        if not r:
            break
        dados = r.json()
        for j in dados.get("data", []):
            if j.get("expired") or j.get("active") is False:
                continue
            pub = j.get("createdAt")
            if pub and datetime.fromisoformat(pub) < corte:
                continue
            empresa = (j.get("company") or {}).get("name") or j.get("companyDisplayName") or ""
            local = ", ".join(x for x in (j.get("city"), j.get("state")) if x)
            modelo = {"remote": "remoto", "hybrid": "hibrido"}.get(j.get("type"), j.get("type"))
            pagina_vaga = f"https://remotar.com.br/job/{j['id']}"
            externo = j.get("externalLink") if j.get("isExternalLink") else None
            vagas.append({
                "id": f"remotar:{j['id']}",
                "fonte": "remotar",
                "titulo": (j.get("title") or "").strip(),
                "empresa": empresa.strip(),
                "local": local or ("Remoto, Brasil" if modelo == "remoto" else ""),
                "modelo_trabalho": modelo,
                "url": pagina_vaga,
                "url_aplicacao": externo or pagina_vaga,
                "tipo_aplicacao": detectar_plataforma(externo) if externo else "remotar",
                "descricao": html_para_texto(j.get("description", "")),
                "publicada_em": pub,
            })
        if pagina >= (dados.get("meta") or {}).get("last_page", 1):
            break
        time.sleep(0.5)
    return vagas


# ---------------------------------------------------------------- vagas.com.br
_NIVEL_VAGASCOM_FORA = ("estagio", "junior", "trainee", "pleno", "auxiliar", "operacional", "tecnico")


def _slug(txt: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def vagascom(termo: str) -> list[dict]:
    r = _get(f"https://www.vagas.com.br/vagas-de-{_slug(termo)}?ordenar_por=mais_recentes")
    if not r:
        return []
    vagas = []
    for li in BeautifulSoup(r.text, "html.parser").select("li.vaga"):
        a = li.select_one("a.link-detalhes-vaga")
        if not a or not a.get("data-id-vaga"):
            continue
        nivel = li.select_one(".nivelVaga")
        nivel = _slug(nivel.get_text(" ", strip=True) if nivel else "").replace("-", " ")
        if any(x in nivel for x in _NIVEL_VAGASCOM_FORA):
            continue
        local = li.select_one(".vaga-local")
        tooltip = local.select_one(".tooltip-place") if local else None
        if tooltip:
            tooltip.decompose()
        empresa = li.select_one(".emprVaga")
        url = "https://www.vagas.com.br" + a["href"]
        vagas.append({
            "id": f"vagascom:{a['data-id-vaga']}",
            "fonte": "vagascom",
            "titulo": (a.get("title") or a.get_text(" ", strip=True)).strip(),
            "empresa": empresa.get_text(" ", strip=True) if empresa else "",
            "local": (local.get_text(" ", strip=True) if local else "").replace(" / ", ", "),
            "modelo_trabalho": None,
            "url": url,
            "url_aplicacao": url,
            "tipo_aplicacao": "vagas.com",
            "descricao": None,
            "publicada_em": None,
        })
    return vagas


def vagascom_detalhar(vaga: dict) -> dict:
    r = _get(vaga["url"])
    time.sleep(random.uniform(1.0, 2.0))
    if not r:
        return vaga
    s = BeautifulSoup(r.text, "html.parser")
    desc = s.select_one(".job-tab-content") or s.select_one(".job-description")
    partes = []
    for sel, rot in ((".job-hierarchylist", "Nível"), (".info-modelo-contratual", "Regime"), (".info-localizacao", "Local")):
        e = s.select_one(sel)
        if e:
            partes.append(f"{rot}: {e.get_text(' ', strip=True)}")
    vaga["descricao"] = ("\n".join(partes) + "\n\n" + (desc.get_text("\n", strip=True) if desc else "")).strip()
    texto = (vaga["titulo"] + " " + vaga["local"] + " " + vaga["descricao"]).lower()
    if "home office" in texto or "remot" in texto:
        vaga["modelo_trabalho"] = "remoto"
    elif "híbrid" in texto or "hibrid" in texto:
        vaga["modelo_trabalho"] = "hibrido"
    return vaga


def detalhar(vaga: dict) -> dict:
    """Completa descrição e modelo de trabalho das fontes que só trazem o resumo na busca."""
    if vaga["fonte"] == "linkedin":
        return linkedin_detalhar(vaga)
    if vaga["fonte"] == "vagascom":
        return vagascom_detalhar(vaga)
    return vaga


# ---------------------------------------------------------------- Google Vagas (SerpApi)
# Ordem de preferência do link de candidatura: direto na plataforma da empresa, depois LinkedIn, depois o resto.
# Indeed e Glassdoor bloqueiam automação, ficam por último.
_ATS_DIRETO = ("gupy.io", "greenhouse.io", "lever.co", "ashbyhq.com", "inhire", "solides", "workable", "teamtailor",
               "smartrecruiters", "recrutei", "kenoby", "abler", "pandape", "bamboohr", "myworkdayjobs", "breezy")
_AGREGADOR_RUIM = ("indeed.", "glassdoor.", "jooble", "talent.com", "bebee", "jobrapido", "trabalhabrasil", "empregos.com")


def _melhor_link(opcoes: list[dict]) -> str | None:
    def nota(o):
        u = (o.get("link") or "").lower()
        if any(x in u for x in _ATS_DIRETO):
            return 0
        if "linkedin.com" in u:
            return 1
        if any(x in u for x in _AGREGADOR_RUIM):
            return 3
        return 2
    links = sorted((o for o in opcoes or [] if o.get("link")), key=nota)
    return links[0]["link"] if links else None


def serpapi_cota(chave: str) -> int:
    """Buscas que ainda restam no mês (consultar a conta não gasta busca)."""
    r = _get(f"https://serpapi.com/account.json?api_key={chave}")
    return int((r.json() if r else {}).get("total_searches_left") or 0)


def google_vagas(consulta: dict, chave: str) -> list[dict]:
    """Uma busca no Google Vagas pela SerpApi (gasta 1 busca da cota, traz até 10 vagas)."""
    import hashlib
    params = {"engine": "google_jobs", "q": consulta["q"], "hl": "pt", "gl": "br", "api_key": chave,
              "location": consulta.get("local", "Brazil")}
    if consulta.get("remoto"):
        params["ltype"] = "1"
    try:
        r = S.get("https://serpapi.com/search.json", params=params, timeout=60)
    except requests.RequestException:
        return []
    if r.status_code != 200:
        return []
    vagas = []
    for j in r.json().get("jobs_results", []):
        ext = j.get("detected_extensions") or {}
        local = j.get("location") or ""
        texto = f"{j.get('title', '')} {local}".lower()
        remoto = ext.get("work_from_home") or consulta.get("remoto") or "remot" in texto or "qualquer lugar" in texto
        link = _melhor_link(j.get("apply_options"))
        vagas.append({
            "id": "google:" + hashlib.sha1((j.get("job_id") or link or j.get("title", "")).encode()).hexdigest()[:16],
            "fonte": "google",
            "titulo": (j.get("title") or "").strip(),
            "empresa": (j.get("company_name") or "").strip(),
            "local": local + (" (remoto)" if remoto and "remot" not in local.lower() else ""),
            "modelo_trabalho": "remoto" if remoto else None,
            "url": j.get("share_link") or link,
            "url_aplicacao": link,
            "tipo_aplicacao": detectar_plataforma(link) if link else "outra",
            "descricao": (j.get("description") or "") + (f"\n\n[Publicada] {ext['posted_at']}" if ext.get("posted_at") else ""),
            "publicada_em": None,
        })
    return vagas


# ---------------------------------------------------------------- Vagas remotas internacionais
# Só entram vagas abertas a quem mora no Brasil: sem restrição de país, ou Brasil, LATAM, Américas ou "worldwide".
_GEO_OK = ("worldwide", "anywhere", "global", "latam", "latin america", "south america", "americas",
           "brazil", "brasil")
_GEO_FORA = ("only", "us-based", "u.s.")


def _geo_aceita(geo) -> bool:
    if isinstance(geo, list):
        geo = ", ".join(geo)
    g = (geo or "").lower().strip()
    if not g:
        return True
    if any(x in g for x in _GEO_FORA) and "brazil" not in g and "brasil" not in g:
        return False
    return any(x in g for x in _GEO_OK)


def _remota(fonte, jid, titulo, empresa, geo, url, desc, pub) -> dict:
    return {"id": f"{fonte}:{jid}", "fonte": fonte, "titulo": html.unescape(titulo or "").strip(),
            "empresa": (empresa or "").strip(), "local": f"Remoto ({geo or 'Worldwide'})", "modelo_trabalho": "remoto",
            "url": url, "url_aplicacao": url, "tipo_aplicacao": detectar_plataforma(url) if url else "outra",
            "descricao": html_para_texto(desc or ""), "publicada_em": pub}


def himalayas(termo: str, paginas: int = 3) -> list[dict]:
    vagas = []
    for p in range(1, paginas + 1):
        r = _get(f"https://himalayas.app/jobs/api/search?q={quote(termo)}&page={p}")
        if not r:
            break
        jobs = r.json().get("jobs", [])
        for j in jobs:
            geo = ", ".join(j.get("locationRestrictions") or [])
            if not _geo_aceita(geo):
                continue
            pub = j.get("pubDate")
            pub = datetime.fromtimestamp(int(pub), timezone.utc).isoformat() if str(pub or "").isdigit() else pub
            link = j.get("applicationLink") or j.get("guid")
            vagas.append(_remota("himalayas", _slug(link.rsplit("/companies/", 1)[-1]), j.get("title"),
                                 j.get("companyName"), geo, link, j.get("description"), pub))
        if len(jobs) < 20:
            break
        time.sleep(0.5)
    return vagas


def remotive(termo: str) -> list[dict]:
    r = _get(f"https://remotive.com/api/remote-jobs?search={quote(termo)}&limit=100")
    if not r:
        return []
    return [_remota("remotive", j["id"], j.get("title"), j.get("company_name"), j.get("candidate_required_location"),
                    j.get("url"), j.get("description"), j.get("publication_date"))
            for j in r.json().get("jobs", []) if _geo_aceita(j.get("candidate_required_location"))]


def jobicy(tag: str) -> list[dict]:
    r = _get(f"https://jobicy.com/api/v2/remote-jobs?count=100&tag={quote(tag)}")
    if not r:
        return []
    return [_remota("jobicy", j["id"], j.get("jobTitle"), j.get("companyName"), j.get("jobGeo"),
                    j.get("url"), j.get("jobDescription"), j.get("pubDate"))
            for j in r.json().get("jobs", []) if _geo_aceita(j.get("jobGeo"))]


def remoteok(tag: str) -> list[dict]:
    r = _get(f"https://remoteok.com/api?tag={quote(tag)}")
    if not r:
        return []
    return [_remota("remoteok", j["id"], j.get("position"), j.get("company"), j.get("location"),
                    j.get("url"), j.get("description"), j.get("date"))
            for j in r.json()[1:] if isinstance(j, dict) and j.get("id") and _geo_aceita(j.get("location"))]
