# Auditoría y propuesta — 11 de noviembre de 2026

## Punto de partida

El proyecto anterior mezcla sesiones Streamlit, capturador y persistencia local.
El proceso debía existir antes de los cortes; una pestaña nueva no recupera precios
que nadie observó. SQLite y los CSV locales no se sincronizan con Streamlit Cloud.
Home prueba B contiene el score aprobado; se conserva en una copia independiente
de sus módulos de cálculo, sin importar la aplicación original en tiempo de ejecución.
Las modificaciones locales anteriores se dejan intactas, incluido su estado Git.

## Arquitectura implementada

```text
Yahoo → worker independiente → SQLite (quotes, barras, cortes inmutables)
                                  ↓
                          API local de lectura → navegador
                                  ↑
                          importación CSV / legado
```

La web lee cortes persistidos y calcula una vista con los pesos experimentales
a partir de los datos guardados. Conserva el score original y no escribe el corte.
Un worker con bloqueo de instancia administra preparación,
reconexión y cortes; el supervisor lo reinicia después de fallos. El calendario
XNYS gobierna festivos, horario de verano y cierre de sesión. Los datos atrasados,+las capturas perdidas y las importaciones deben identificarse.

## Opciones y costo

| Opción | Costo de servicio | Dependencia y límites | Decisión |
|---|---|---|---|
| PC existente + proceso programado + SQLite | Sin suscripción; energía/internet propios | PC despierta y conectada; sin garantía de Yahoo | Implementada en esta fase |
| Streamlit Community Cloud | Plan gratuito | Hiberna tras 12h sin tráfico; almacenamiento generado no garantizado | No usar como capturador permanente |
| GitHub Actions programado | Cuota gratuita según cuenta/repositorio | Cron puede retrasarse o descartarse; no precisión al segundo | Sólo tareas históricas futuras |
| Servidor dedicado o VPS | Depende del proveedor | Requiere operación, seguridad y cuota | Evaluar antes de publicar 24/7 |
| Alpaca Basic | Gratuito | IEX, máximo30 símbolos WebSocket; opciones indicativas | No reemplaza transparentemente cobertura72 |

No se ha demostrado una alternativa gratuita que garantice cobertura completa de
72 símbolos y captura de apertura a diez segundos. Yahoo vía yfinance se mantiene
como proveedor experimental con registros de edad, recepción y disponibilidad.
Que el software esté listo para capturar no garantiza que el proveedor envíe
cotizaciones suficientes a tiempo. No se realizan suscripciones de pago.

## Diseño

Escáner: estado del servicio, relojes NY/Hermosillo, cobertura, fuente, cortes,
lista ordenada, score/100, detalles y gráfica prominente. Historial: fecha y corte
guardado con los mismos componentes. Modo externo e instantánea del corte se
identifican por separado. No hay botones de comprar ni controles ficticios.

## Fases y aceptación

1. Fase actual: coexistencia; importación real; score experimental visible con el previo para comparar; persistencia
   después de cerrar/reabrir la web; calendario y pruebas de cortes sin información
   futura; API/UI local; capturador independiente y procedimiento de autoinicio.
   Una apertura futura real es necesaria para medir latencia y reconexión de Yahoo.
2. Publicación: elegir almacenamiento duradero y proceso alojado; probar acceso
   tardío y recuperación sin ordenador personal. Verificar cuotas y derechos de datos.
3. Cuentas: autenticación gestionada, aislamiento de datos y preferencias.
4. Simulador: contratos existentes, bid/ask reales, timestamps, spread, multiplicador,
   comisiones y reglas de fill/expiración; no sustituir cotizaciones por valores
   indicativos sin identificarlos. Validar fuente antes de implementar opciones.
5. Broker: confirmar Charles Schwab, API oficial y autorización por operación;
   recomendaciones y salidas sólo después de definir la estrategia y validarla.

## Fuentes oficiales consultadas

- [Streamlit: gestión, límites e hibernación](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)
- [Streamlit: persistencia de archivos](https://docs.streamlit.io/develop/concepts/configuration/serving-static-files)
- [Alpaca: planes y cobertura](https://docs.alpaca.markets/us/docs/about-market-data-api)
- [Alpaca: opciones indicativas y OPRA](https://docs.alpaca.markets/us/docs/historical-option-data)
- [TradingView: widget oficial de gráfica avanzada](https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/)
- [GitHub: retrasos de tareas programadas](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)
- [Schwab Trader API](https://developer.schwab.com/products/trader-api--individual)

Los límites de los proveedores pueden cambiar. El widget no comparte necesariamente
el feed del escáner; no se utiliza su gráfica para alimentar el score.
