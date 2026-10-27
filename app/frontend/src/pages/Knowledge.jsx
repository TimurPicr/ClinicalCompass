import React, { useState } from "react";
import { Search, BookOpen, Upload, RefreshCw, FileText } from "lucide-react";
import { api } from "../api/client";
import {
  useData,
  useAction,
  DataState,
  Section,
  Empty,
  DateText,
  Field,
  Submit,
  ErrorBox,
  SourceLink,
} from "../components/common";
const categories = {
  drug_instruction: "Инструкции к препаратам",
  clinical_guideline: "Клинические рекомендации",
  publication: "Научные публикации",
};
export default function Knowledge() {
  const sources = useData("/knowledge/sources"),
    action = useAction();
  const [query, setQuery] = useState(""),
    [category, setCategory] = useState(""),
    [results, setResults] = useState(null),
    [searchError, setSearchError] = useState(""),
    [searching, setSearching] = useState(false);
  async function search(e) {
    e.preventDefault();
    setSearching(true);
    setSearchError("");
    try {
      setResults(
        await api(
          `/knowledge/search?q=${encodeURIComponent(query)}&category=${category}`,
        ),
      );
    } catch (e) {
      setSearchError(e.message);
    } finally {
      setSearching(false);
    }
  }
  async function upload(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const result = await action.run(
      () =>
        api("/knowledge/import", { method: "POST", body: new FormData(form) }),
      "Источник импортирован",
    );
    if (result) form.reset();
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ПРОВЕРЯЕМЫЕ ИСТОЧНИКИ</span>
          <h1>Медицинская база знаний</h1>
          <p>
            Локальный поиск по рекомендациям, инструкциям и научным публикациям.
          </p>
        </div>
        <button
          className="btn secondary"
          disabled={action.pending}
          onClick={() =>
            action.run(
              () => api("/knowledge/sync", { method: "POST" }),
              "Проверка источников добавлена в очередь",
            )
          }
        >
          <RefreshCw size={16} />
          Проверить обновления
        </button>
      </div>
      <Section
        title="Поиск по источникам"
        sub="Поиск по тексту, метаданным и семантической близости"
      >
        <form onSubmit={search} className="knowledge-search">
          <div className="search-box">
            <Search size={18} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              required
              minLength="2"
              placeholder="Препарат, действующее вещество или клинический вопрос"
              aria-label="Поисковый запрос"
            />
          </div>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            aria-label="Категория источников"
          >
            <option value="">Все категории</option>
            {Object.entries(categories).map(([key, label]) => (
              <option value={key} key={key}>
                {label}
              </option>
            ))}
          </select>
          <Submit pending={searching}>Найти</Submit>
        </form>
        <ErrorBox error={searchError} />
        {results && (
          <>
            <p className="search-mode">
              {results.semantic_available
                ? "Семантический и текстовый поиск доступны"
                : "Семантический поиск недоступен; показаны результаты текстового поиска"}
            </p>
            {results.results?.length ? (
              <div className="knowledge-results">
                {results.results.map((r, i) => (
                  <div key={r.id || i} className="knowledge-result">
                    <h3>
                      <SourceLink url={r.url}>{r.title}</SourceLink>
                    </h3>
                    <span className="tag">{r.source}</span>
                    <p>{r.text}</p>
                    <small>
                      Документ #{r.document_id}
                      {r.page && ` · страница ${r.page}`}
                    </small>
                  </div>
                ))}
              </div>
            ) : (
              <Empty>По вашему запросу ничего не найдено</Empty>
            )}
          </>
        )}
      </Section>
      <div className="two-col knowledge-columns">
        <Section
          title="Импорт источника"
          sub="PDF или UTF-8 TXT с правомерным доступом к тексту"
        >
          <form className="form-stack" onSubmit={upload}>
            <Field label="Название">
              <input name="title" required />
            </Field>
            <div className="form-grid">
              <Field label="Категория">
                <select name="category">
                  {Object.entries(categories).map(([key, label]) => (
                    <option value={key} key={key}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Источник">
                <select name="source">
                  <option value="local">Локальный импорт</option>
                  <option value="grls">ГРЛС</option>
                  <option value="minzdrav">Минздрав РФ</option>
                  <option value="pubmed">PubMed</option>
                </select>
              </Field>
            </div>
            <Field label="Ссылка на первоисточник">
              <input type="url" name="url" required placeholder="https://…" />
            </Field>
            <div className="form-grid">
              <Field label="Внешний идентификатор">
                <input
                  name="external_id"
                  placeholder="PMID или идентификатор источника"
                />
              </Field>
              <Field label="Версия">
                <input name="version" defaultValue="1" />
              </Field>
            </div>
            <Field label="Исходный документ">
              <input
                type="file"
                name="file"
                accept="application/pdf,text/plain"
                required
              />
            </Field>
            <ErrorBox error={action.error} />
            <Submit pending={action.pending}>
              <Upload size={15} />
              Импортировать
            </Submit>
          </form>
        </Section>
        <Section title="Документы в базе">
          <DataState request={sources}>
            {sources.data?.documents?.length ? (
              <div className="source-documents">
                {sources.data.documents.map((doc) => (
                  <div className="source-document" key={doc.id}>
                    <FileText size={18} />
                    <div>
                      <h3>
                        <SourceLink url={doc.url}>{doc.title}</SourceLink>
                      </h3>
                      <p>
                        {categories[doc.category] || doc.category} ·{" "}
                        {doc.source === "demo"
                          ? "СИНТЕТИЧЕСКИЙ ПРИМЕР"
                          : doc.source}
                      </p>
                      <span className="tag">
                        {doc.active ? "Проиндексирован" : "Ожидает индексации"}
                      </span>
                      {doc.published_at && (
                        <p>
                          Опубликован{" "}
                          <DateText value={doc.published_at} time={false} />
                        </p>
                      )}
                      <small>
                        Версия {doc.version} · Загружен{" "}
                        <DateText value={doc.downloaded_at} />
                      </small>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Empty icon={BookOpen}>Импортируйте первый источник</Empty>
            )}
          </DataState>
        </Section>
      </div>
      <Section
        title="Журнал обновлений"
        sub="Ограничения внешних источников и ошибки загрузки отображаются явно"
      >
        <DataState request={sources}>
          {sources.data?.logs?.length ? (
            <div className="list">
              {sources.data.logs.map((log) => (
                <div className="list-item" key={log.id}>
                  <span className="tag">{log.source}</span>
                  <div className="grow">
                    <strong>{log.message}</strong>
                    <small>
                      <DateText value={log.created_at} />
                    </small>
                  </div>
                  <span className="tag">{log.status}</span>
                </div>
              ))}
            </div>
          ) : (
            <Empty>Журнал пока пуст</Empty>
          )}
        </DataState>
      </Section>
    </>
  );
}
