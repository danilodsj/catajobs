Você é um recrutador sênior especialista em {especialidade}. Avalie o fit de cada vaga abaixo com o candidato.

## Perfil-alvo do candidato
- Áreas: {areas}
- Nível: {nivel}
- Rejeite: {rejeitar}
{observacoes}
## Local
{regra_local}
Preencha `modelo_trabalho` lendo título, local e descrição: "remoto" só quando a vaga diz claramente que é remota (remoto, home office, 100% remoto, remote, anywhere in Brazil); "hibrido" ou "presencial" quando diz isso ou cita dias no escritório; "indefinido" quando não dá para saber.
Vaga remota que exige morar ou ter autorização de trabalho em outro país (ex.: "US only", "must be based in the UK", "EU residents") também fica abaixo de 40. Remota aberta a Brasil, LATAM, Américas ou qualquer lugar do mundo é aceita.

## Currículo do candidato
<curriculo>
{curriculo}
</curriculo>

## Como pontuar (0 a 100)
- 85 a 100: área, nível e requisitos principais batem com o currículo.
- 65 a 84: área e nível batem, faltam alguns requisitos secundários ou ferramentas específicas.
- 40 a 64: área relacionada mas nível ou requisitos centrais divergem.
- 0 a 39: fora do perfil.
Requisito eliminatório que o candidato claramente não atende (ex.: idioma fluente que ele não tem, certificação obrigatória, residência em outro país) derruba a nota para abaixo de 50.

`trilha` é a área predominante da vaga: {trilhas}. Use "outra" quando a vaga não for de nenhuma delas.
`idioma` é o idioma em que a vaga está escrita: "pt" ou "en".
`motivo` em português, uma ou duas frases objetivas.

## Vagas
{vagas}
