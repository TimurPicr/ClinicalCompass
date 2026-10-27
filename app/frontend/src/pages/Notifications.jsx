import React, { useEffect, useState } from "react";
import { Bell, BellOff, Smartphone, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import {
  useData,
  useAction,
  DataState,
  Section,
  Field,
  ErrorBox,
  Loading,
} from "../components/common";
function keyBytes(value) {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  return Uint8Array.from(
    atob((value + padding).replace(/-/g, "+").replace(/_/g, "/")),
    (c) => c.charCodeAt(0),
  );
}
export default function Notifications() {
  const request = useData("/notifications/status"),
    action = useAction();
  const [supported] = useState(
      () =>
        typeof Notification !== "undefined" &&
        "serviceWorker" in navigator &&
        "PushManager" in window,
    ),
    [subscription, setSubscription] = useState(null);
  useEffect(() => {
    if (supported)
      navigator.serviceWorker.ready
        .then((r) => r.pushManager.getSubscription())
        .then(setSubscription);
  }, [supported]);
  async function enable() {
    await action.run(async () => {
      const config = await api("/notifications/public-key");
      if (!config.enabled || !config.public_key)
        throw new Error(
          "Web Push не настроен на сервере. Необходимо добавить ключи VAPID в .env.",
        );
      const permission = await Notification.requestPermission();
      if (permission !== "granted")
        throw new Error(
          "Разрешение на уведомления не получено. Измените настройки этого сайта в браузере.",
        );
      const registration = await navigator.serviceWorker.ready;
      let sub = await registration.pushManager.getSubscription();
      if (!sub)
        sub = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: keyBytes(config.public_key),
        });
      await api("/notifications/subscribe", {
        method: "POST",
        body: sub.toJSON(),
      });
      setSubscription(sub);
      return true;
    }, "Напоминания включены на этом устройстве");
  }
  async function disable() {
    await action.run(async () => {
      if (subscription) {
        await api("/notifications/subscribe", {
          method: "DELETE",
          body: { endpoint: subscription.endpoint },
        });
        await subscription.unsubscribe();
        setSubscription(null);
      }
      return true;
    }, "Напоминания отключены");
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">ВАШ ЕЖЕДНЕВНЫЙ РИТМ</span>
          <h1>Напоминания</h1>
          <p>Небольшая поддержка, чтобы не забыть о важных делах.</p>
        </div>
      </div>
      <Section
        title="Уведомления на этом устройстве"
        sub="Расписание препаратов, опросников и дневника задаёт лечащий врач"
      >
        <DataState request={request}>
          <div className="notification-setting">
            <span className="task-icon mint">
              <Bell size={25} />
            </span>
            <div className="grow">
              <h3>
                {subscription
                  ? "Напоминания включены"
                  : "Напоминания пока отключены"}
              </h3>
              <p>
                {request.data?.configured
                  ? "Сервер готов к отправке напоминаний."
                  : "Web Push ещё не настроен на локальном сервере."}
              </p>
              <small>
                Подписок в аккаунте: {request.data?.subscriptions || 0}
              </small>
            </div>
            <button
              className="btn"
              disabled={action.pending || !supported}
              onClick={subscription ? disable : enable}
            >
              {subscription ? <BellOff size={17} /> : <Bell size={17} />}{" "}
              {subscription ? "Отключить" : "Включить"}
            </button>
          </div>
        </DataState>
        <ErrorBox error={action.error} />
        {!supported && (
          <div className="notice">
            Этот браузер не поддерживает Web Push. На iPhone установите
            приложение на домашний экран через меню «Поделиться» в Safari и
            откройте его оттуда.
          </div>
        )}
      </Section>
      <div className="two-col">
        <Section title="Установка на телефон">
          <div className="info-card">
            <Smartphone size={27} />
            <div>
              <p>
                Откройте меню браузера и выберите «Добавить на главный экран».
                На поддерживаемых версиях iOS уведомления доступны для
                установленного веб-приложения.
              </p>
            </div>
          </div>
        </Section>
        <Section title="Приватность уведомлений">
          <div className="info-card">
            <ShieldCheck size={27} />
            <div>
              <p>
                Текст напоминаний не содержит названий препаратов, диагноза или
                медицинских подробностей.
              </p>
              <p>
                Напоминания отправляются, пока локальный сервер и фоновый
                обработчик работают.
              </p>
            </div>
          </div>
        </Section>
      </div>
    </>
  );
}
