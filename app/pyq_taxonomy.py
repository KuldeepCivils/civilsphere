"""Our own subject / topic labels for past questions, based on the public UPSC syllabus headings.
A question is scored against each topic's keyword list; the topic with most hits wins."""
import re

RULES = [
 # (subject, topic, comma-separated keywords; multi-word phrases count double)
 ("Indian Polity", "Constitution: features and amendments", "constitution,amendment,preamble,basic structure,fundamental duties,constituent assembly,article 368,schedule of the constitution,constitutional"),
 ("Indian Polity", "Fundamental Rights and DPSP", "fundamental right,directive principles,writ,habeas corpus,mandamus,right to equality,right to privacy,freedom of speech,article 21,article 19,article 14"),
 ("Indian Polity", "Parliament and legislatures", "lok sabha,rajya sabha,parliament,speaker,money bill,ordinance,legislative council,legislative assembly,anti-defection,budget session,private member"),
 ("Indian Polity", "Executive, President and Governor", "president of india,governor,prime minister,council of ministers,cabinet,vice-president,attorney general,pardon,chief minister"),
 ("Indian Polity", "Judiciary", "supreme court,high court,judge,judicial review,public interest litigation,lok adalat,tribunal,contempt,collegium,judiciary"),
 ("Indian Polity", "Federalism and local government", "panchayat,municipal,73rd amendment,74th amendment,gram sabha,finance commission,centre-state,inter-state council,union territory,fifth schedule,sixth schedule,local self-government"),
 ("Indian Polity", "Elections and constitutional bodies", "election commission,electoral,comptroller and auditor general,union public service commission,representation of the people,delimitation,model code of conduct,electoral bond"),
 ("Indian Polity", "Governance, laws and schemes", "right to information,lokpal,lokayukta,e-governance,citizen charter,statutory body,non-governmental,self-help group,good governance"),
 ("Indian Economy", "Banking and monetary policy", "reserve bank,repo rate,monetary policy,npa,non-performing,inflation targeting,cash reserve ratio,statutory liquidity,payment bank,nbfc,basel,bank,credit,loan"),
 ("Indian Economy", "Fiscal policy, budget and taxation", "fiscal deficit,budget,gst,goods and services tax,tax,subsidy,frbm,revenue deficit,public debt,government expenditure,direct tax,finance bill"),
 ("Indian Economy", "Inflation, growth and national income", "gdp,gnp,gross domestic product,inflation,wholesale price index,consumer price index,national income,economic growth,deflator,unemployment,per capita income"),
 ("Indian Economy", "External sector and trade", "world trade organization,wto,exports,imports,balance of payments,current account,exchange rate,rupee,foreign direct investment,fdi,trade agreement,tariff,foreign exchange"),
 ("Indian Economy", "Capital markets and financial instruments", "sebi,share market,bond,debenture,mutual fund,derivative,stock exchange,sensex,insurance,pension,securities"),
 ("Indian Economy", "Agriculture and food", "agriculture,minimum support price,crop,farmer,irrigation,public distribution,food security,fertiliser,green revolution,horticulture,kharif,rabi"),
 ("Indian Economy", "Industry, infrastructure and planning", "industrial,msme,niti aayog,five year plan,infrastructure,make in india,special economic zone,railway,port,industry"),
 ("Indian Economy", "International economic institutions", "international monetary fund,imf,world bank,asian development bank,brics,asian infrastructure investment bank,bretton woods,new development bank,special drawing rights"),
 ("Geography", "Physical geography and geomorphology", "earthquake,volcano,plate tectonics,mountain,rock,weathering,landform,erosion,continental drift,glacier"),
 ("Geography", "Climatology and oceanography", "monsoon,cyclone,el nino,la nina,jet stream,ocean current,tide,atmosphere,rainfall,climate,temperature,pressure belt,trade winds"),
 ("Geography", "Indian geography: rivers, soils and resources", "river,basin,tributary,soil,mineral,coal,iron ore,plateau,western ghats,himalaya,delta,coastal plain,lake"),
 ("Geography", "World geography and places", "strait,desert,island,sea,gulf,continent,latitude,longitude,boundary,bordering"),
 ("Geography", "Human and economic geography", "population,census,urbanisation,migration,settlement,transport,location of industries,density"),
 ("Environment & Ecology", "Biodiversity and conservation", "biodiversity,wildlife sanctuary,national park,tiger reserve,endangered,iucn,red list,biosphere reserve,ramsar,wetland,cites,species,conservation"),
 ("Environment & Ecology", "Climate change and pollution", "climate change,greenhouse,carbon,emission,ozone,pollution,unfccc,paris agreement,kyoto,air quality,global warming,pollutant"),
 ("Environment & Ecology", "Ecology and ecosystems", "ecosystem,food chain,biome,ecological succession,habitat,eutrophication,keystone,trophic,ecology"),
 ("Environment & Ecology", "Environmental laws and institutions", "environment protection act,forest rights act,green tribunal,environmental impact assessment,wildlife protection act,biological diversity act,forest conservation"),
 ("Science & Technology", "Space and defence technology", "isro,satellite,launch vehicle,missile,chandrayaan,mangalyaan,gaganyaan,drone,radar,nuclear,defence,orbit,rocket"),
 ("Science & Technology", "Biotechnology and health", "vaccine,virus,bacteria,dna,gene,genetically,crispr,stem cell,disease,antibiotic,biotechnology,enzyme,protein,vitamin,cell,infection"),
 ("Science & Technology", "Information technology and emerging tech", "artificial intelligence,blockchain,quantum,cyber,internet,5g,robotics,nanotechnology,3d printing,software,encryption,microprocessor,computer,digital"),
 ("Science & Technology", "Physics, chemistry and energy", "energy,solar,wind power,renewable,battery,hydrogen,fuel,laser,radiation,element,atom,acid,polymer,electricity,wavelength,gas"),
 ("Science & Technology", "Institutions and missions in S&T", "drdo,csir,department of science,research institute,technology mission"),
 ("Ancient History", "Prehistory and Indus Valley", "palaeolithic,neolithic,mesolithic,harappan,indus valley,chalcolithic,stone age"),
 ("Ancient History", "Vedic age and religions", "vedic,rigveda,upanishad,buddhism,jainism,buddha,mahavira,veda,brahmana,mahajanapada"),
 ("Ancient History", "Mauryas, Guptas and early kingdoms", "maurya,ashoka,gupta,kushana,satavahana,chola,pallava,sangam,harsha,chandragupta"),
 ("Medieval History", "Delhi Sultanate and Mughals", "sultanate,mughal,akbar,aurangzeb,babur,sher shah,delhi sultan,iltutmish,alauddin"),
 ("Medieval History", "Bhakti, Sufi and regional kingdoms", "bhakti,sufi,vijayanagara,bahmani,maratha,shivaji,kabir,nanak,chishti"),
 ("Modern History", "Early colonial rule and reforms", "east india company,regulating act,charter act,permanent settlement,subsidiary alliance,social reform,brahmo samaj,arya samaj,revolt of 1857,governor-general,viceroy"),
 ("Modern History", "National movement", "gandhi,indian national congress,non-cooperation,civil disobedience,quit india,swadeshi,partition of bengal,simon commission,moderates,extremists,khilafat,dandi"),
 ("Modern History", "Constitutional developments and independence", "government of india act,cabinet mission,cripps,mountbatten,transfer of power,round table conference,communal award,morley-minto,montagu-chelmsford"),
 ("Art & Culture", "Architecture, sculpture and painting", "temple,architecture,stupa,sculpture,painting,cave,mural,gandhara,nagara,dravida,miniature"),
 ("Art & Culture", "Performing arts, literature and heritage", "dance,music,kathak,bharatanatyam,raga,folk,theatre,unesco,heritage,literature,festival,handicraft,classical"),
 ("International Relations", "India and the world", "bilateral,summit,saarc,asean,quad,shanghai cooperation,security council,united nations,g20,neighbour"),
 ("International Relations", "Global organisations and agreements", "convention,protocol,world health organization,unesco,unicef,international labour,iaea,nato,opec"),
 ("Society and Social Justice", "Welfare, schemes and demography", "yojana,welfare,scheduled caste,scheduled tribe,tribal,minority,literacy,nutrition,poverty,women empowerment,child"),
]
RULES = [(s, t, [k.strip() for k in kw.split(",") if k.strip()]) for s, t, kw in RULES]
_COMPILED = [(s, t, [(re.compile(r"\b" + re.escape(k) + r"(?:s|es)?\b", re.I), 2 if " " in k or "-" in k else 1) for k in kws]) for s, t, kws in RULES]
SUBJECT_ORDER = []
for s, _, _ in RULES:
    if s not in SUBJECT_ORDER:
        SUBJECT_ORDER.append(s)


def classify(question, options=None):
    """Returns (subject, topic). Falls back to a Current Affairs & Miscellaneous bucket."""
    text = (question or "") + " " + " ".join(options or [])
    best, best_n = None, 0
    for s, t, pats in _COMPILED:
        n = sum(w for p, w in pats if p.search(text))
        if n > best_n:
            best, best_n = (s, t), n
    return best if best else ("Current Affairs & Miscellaneous", "Mixed / other")
