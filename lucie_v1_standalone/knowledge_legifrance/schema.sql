-- Schéma SQLite minimal pour la base Légifrance dérivée du dump DILA LEGI.
--
-- Design : simple et indexé pour retrieval BM25 + matching par référence.
-- Ne reproduit PAS l'intégralité du schéma legi.py (qui gère les versions
-- successives, les liens, les anomalies, etc.) — on garde uniquement
-- ce qui sert le retrieval dans Lucie.
--
-- Une migration vers le schéma legi.py complet est possible ultérieurement
-- si on vient à utiliser tar2sqlite direct.

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS meta (
    key     TEXT PRIMARY KEY,
    value   TEXT
);

INSERT OR IGNORE INTO meta (key, value) VALUES
    ('schema_version', '1'),
    ('source', 'DILA LEGI dump (https://echanges.dila.gouv.fr/OPENDATA/LEGI/)'),
    ('license', 'Licence Ouverte Etalab');

-- Un code juridique (ex : Code du travail, Code civil).
CREATE TABLE IF NOT EXISTS codes (
    cid         TEXT PRIMARY KEY,        -- ex: LEGITEXT000006072050
    titre       TEXT NOT NULL,           -- ex: "Code du travail"
    date_maj    TEXT                     -- ISO-8601 de la dernière MAJ DILA
);

-- Un article unique (version en vigueur).
CREATE TABLE IF NOT EXISTS articles (
    id              TEXT PRIMARY KEY,    -- ex: LEGIARTI000006901007
    code_cid        TEXT NOT NULL REFERENCES codes(cid),
    num             TEXT NOT NULL,       -- ex: "L1233-1" (numéro canonique)
    num_prefix      TEXT,                -- "L" | "R" | "D" | "" (partie législative / réglementaire)
    num_numeric     INTEGER,             -- pour filtrage par range (ex : 1233)
    etat            TEXT,                -- "VIGUEUR" | "ABROGE" | ...
    date_debut      TEXT,                -- ISO date
    date_fin        TEXT,                -- ISO date (nullable si en vigueur)
    texte           TEXT NOT NULL,       -- le contenu textuel de l'article
    nota            TEXT,                -- notes juridiques associées (peut être null)
    url_legifrance  TEXT NOT NULL,       -- URL canonique pour vérification humaine
    mtime           INTEGER              -- timestamp de la dernière modif DILA
);

CREATE INDEX IF NOT EXISTS articles_code_num ON articles (code_cid, num);
CREATE INDEX IF NOT EXISTS articles_num_prefix_numeric ON articles (num_prefix, num_numeric);
CREATE INDEX IF NOT EXISTS articles_etat ON articles (etat);

-- Recherche plein-texte (FTS5 si dispo, sinon fallback LIKE dans retriever).
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    num, texte,
    content='articles',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS articles_fts_ai AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(rowid, num, texte) VALUES (new.rowid, new.num, new.texte);
END;

CREATE TRIGGER IF NOT EXISTS articles_fts_au AFTER UPDATE ON articles BEGIN
    UPDATE articles_fts SET num = new.num, texte = new.texte WHERE rowid = new.rowid;
END;

CREATE TRIGGER IF NOT EXISTS articles_fts_ad AFTER DELETE ON articles BEGIN
    DELETE FROM articles_fts WHERE rowid = old.rowid;
END;

-- Vue matérialisée : articles par thème (indexée par indexer.py depuis theme_mapping.yaml).
CREATE TABLE IF NOT EXISTS articles_by_theme (
    theme_id        TEXT NOT NULL,       -- ex : "droit_social"
    article_id      TEXT NOT NULL REFERENCES articles(id),
    PRIMARY KEY (theme_id, article_id)
);

CREATE INDEX IF NOT EXISTS articles_by_theme_theme ON articles_by_theme (theme_id);

-- Historique des syncs (audit interne + base du diff).
CREATE TABLE IF NOT EXISTS sync_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,                    -- ISO-8601
    archives        TEXT NOT NULL,                    -- JSON array des archives appliquées
    articles_added  INTEGER NOT NULL DEFAULT 0,
    articles_updated INTEGER NOT NULL DEFAULT 0,
    articles_deleted INTEGER NOT NULL DEFAULT 0,
    db_sha256       TEXT,                             -- hash de la DB post-sync
    duration_sec    REAL
);
