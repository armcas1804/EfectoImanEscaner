# Efecto Imán Scanner

Nueva plataforma independiente, primera fase. La aplicación anterior continúa en
`../EfectoIman`; esta carpeta tiene su propio Python, base SQLite y puerto **8601**.
No cambia ni publica el proyecto anterior.

## Abrir

Haz doble clic en **Iniciar.cmd**. Inicia dos procesos ocultos independientes:
la web en <http://127.0.0.1:8601/> y el capturador. Puedes cerrar el navegador;
el capturador sigue funcionando. Los supervisores reinician procesos que fallen.
Para detenerlos: `powershell -File .\Detener.ps1`.

Para arrancar automáticamente al iniciar sesión de Windows, ejecuta una vez
`powershell -ExecutionPolicy Bypass -File .\InstalarInicioAutomatico.ps1`.
El instalador está preparado, pero no se registra sin ejecutarlo. La opción
gratuita implementada requiere esta computadora encendida, conectada y sin
suspenderse durante la apertura. No depende de abrir una pestaña a las 09:25.

## Instalación separada

```powershell
cd C:\Users\armca\Desktop\Bot\EfectoImanScanner
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\Iniciar.cmd
```

La captura usa calendario XNYS, zona America/New_York, cambios de horario,
festivos y cierres anticipados. Prepara velas previas y congela cortes de
10, 30, 60 y 90 segundos. Los datos se guardan en SQLite WAL y se consultan
desde la web. Los cortes son inmutables: volver a abrir la web no los recalcula.
La hora del proveedor y la hora de recepción se guardan por separado.
Si el proceso no observó la apertura, se informa una captura ausente o parcial;
no se reconstruyen supuestos datos de diez segundos con velas posteriores.

## Datos e historial

La importación lee CSVs completos de Home prueba B y registros del proyecto
anterior, sin modificar sus archivos. Se marcan como importados; no certifican
una recepción en vivo por este nuevo capturador.

```powershell
.\.venv\Scripts\python.exe import_data.py --csv "C:\ruta\corte.csv"
.\.venv\Scripts\python.exe import_data.py --legacy "..\EfectoIman"
.\.venv\Scripts\python.exe worker.py --check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

La web y el CSV aplican el score experimental `pattern-b-v1` a los datos del
corte. Conservan la calificación previa para comparar, sin editar los registros
guardados. La regla B de elegibilidad (gap, giro y precio fuera) sigue vigente.
La nueva nota combina lateralidad (30%), delgadez (30%), estabilidad después de
la primera cotización (20%) y distancia exterior relativa al ancho previo (20%).
La media geométrica y un tope por el peor aspecto de las bandas reducen la
compensación entre factores. El gap no aporta puntos adicionales.

Con cotizaciones originales compatibles se mide el mayor movimiento observado
de la banda objetivo y el pico de expansión después de la primera cotización.
Si sólo están los extremos, se indican como tales. El percentil de ancho se
usa cuando hay al menos 10 muestras de sesiones anteriores. Los diagnósticos
sin información suficiente muestran «Sin score». La nota mide el parecido con
el patrón, no una probabilidad de reversión.

## Gráficas

«Mercado externo» utiliza el widget oficial de TradingView en 15 minutos con
Bandas de Bollinger. Es una fuente externa: su mercado, ajustes, retraso y sesión
pueden diferir de Yahoo. No representa el corte histórico seleccionado. El enlace
a Yahoo permite contrastar. El indicador de retraso del proveedor debe revisarse.

«Vista del corte» muestra solamente velas previas guardadas, precios observados y
bandas provisionales del corte. No inventa velas subminuto ni una trayectoria entre
dos cotizaciones. Si un CSV carece de OHLC previos, se muestran sólo sus observaciones.

## Alcance de esta fase

Web local de lectura, escáner autónomo, calendario, persistencia, diagnóstico,
historial, exportación, desglose del score y arranque independiente. No contiene
cuentas, órdenes, simulador de contratos ni credenciales de broker. El puerto se
limita a localhost; no exponer directamente este servidor a Internet. Una futura
publicación multiusuario requiere alojamiento, HTTPS, autenticación y almacenamiento
duradero adecuados.

Consulta `docs/ARQUITECTURA.md` para auditoría, alternativas gratuitas, fuentes y
criterios de aceptación. Los registros operativos se escriben en `logs/`.
