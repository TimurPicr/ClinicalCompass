import { useEffect, useState } from "react";
import "./App.css";


const API_URL = "http://127.0.0.1:8000";


interface Question {
  id: number;
  text: string;
  options: string[];
}


interface Questionnaire {
  id: string;
  title: string;
  questions: Question[];
}


interface QuestionnaireResult {
  score: number;
  max_score: number;
  note: string;
}


interface Recommendation {
  code: string;
  category: "mandatory" | "desirable";
  title: string;
  description: string;
  source: string;
}


function App() {

  const [recommendations, setRecommendations] =
  useState<Recommendation[]>([]);

  const [questionnaire, setQuestionnaire] =
    useState<Questionnaire | null>(null);

  const [answers, setAnswers] =
    useState<Record<number, number>>({});

  const [result, setResult] =
    useState<QuestionnaireResult | null>(null);

  const [error, setError] = useState("");


  useEffect(() => {
    fetch(`${API_URL}/api/questionnaires/demo`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("Ошибка загрузки вопросов");
        }

        return response.json();
      })
      .then((data: Questionnaire) => {
        setQuestionnaire(data);
      })
      .catch(() => {
        setError("Не удалось загрузить опросник");
      });
  }, []);


  function selectAnswer(
    questionId: number,
    answer: number
  ) {
    setAnswers((previous) => ({
      ...previous,
      [questionId]: answer,
    }));

    setResult(null);
  }


  async function submitAnswers() {
    if (!questionnaire) {
      return;
    }

    const answerList = questionnaire.questions.map(
      (question) => answers[question.id]
    );

    const recommendationResponse = await fetch(
  `${API_URL}/api/recommendations/preview`,
  {
    method: "POST",

    headers: {
      "Content-Type": "application/json",
    },

    body: JSON.stringify({
      answers: answerList,
      urgent_help_requested: false,
    }),
  }
);

if (!recommendationResponse.ok) {
  throw new Error("Не удалось получить рекомендации");
}

const recommendationData = await recommendationResponse.json();

setRecommendations(
  recommendationData.recommendations
);

    try {
      setError("");

      const response = await fetch(
        `${API_URL}/api/questionnaires/demo/submit`,
        {
          method: "POST",

          headers: {
            "Content-Type": "application/json",
          },

          body: JSON.stringify({
            answers: answerList,
          }),
        }
      );

      if (!response.ok) {
        throw new Error("Ошибка отправки ответов");
      }

      const data: QuestionnaireResult =
        await response.json();

      setResult(data);

    } catch {
      setError("Не удалось отправить ответы");
    }
  }


  if (!questionnaire) {
    return (
      <div className="container">
        {error || "Загрузка опросника..."}
      </div>
    );
  }


  const allAnswered = questionnaire.questions.every(
    (question) => answers[question.id] !== undefined
  );


  return (
    <main className="container">

      {recommendations.length > 0 && (
        <section>
          <h2>Рекомендации</h2>

          {recommendations.map((item) => (
            <div key={item.code}>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
            </div>
          ))}
        </section>
      )}

      <h1>Clinical Compass</h1>

      <h2>{questionnaire.title}</h2>

      <p>
        Демонстрационный опросник.
        Не предназначен для медицинской диагностики.
      </p>

      {questionnaire.questions.map((question) => (

        <fieldset
          key={question.id}
          className="question"
        >

          <legend>{question.text}</legend>

          {question.options.map((option, index) => (

            <label key={index} className="option">

              <input
                type="radio"
                name={`question-${question.id}`}
                checked={
                  answers[question.id] === index
                }
                onChange={() =>
                  selectAnswer(question.id, index)
                }
              />

              {option}

            </label>

          ))}

        </fieldset>

      ))}

      <button
        onClick={submitAnswers}
        disabled={!allAnswered}
      >
        Завершить опрос
      </button>

      {result && (
        <div className="result">

          <h3>Результат</h3>

          <p>
            Баллов: {result.score} из {result.max_score}
          </p>

          <p>{result.note}</p>

        </div>
      )}

      {error && <p className="error">{error}</p>}

    </main>
  );
}


export default App;