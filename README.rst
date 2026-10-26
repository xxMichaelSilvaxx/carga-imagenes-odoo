========================
Carga de imágenes a Odoo
========================

.. image:: codigo_fuente_aplicativo/icon.png
   :width: 96
   :alt: Icono de Carga de imágenes a Odoo

Aplicativo de escritorio para **convertir fotos de productos a WebP y subirlas a Odoo 19**
de forma masiva, identificando cada producto por su referencia interna. No requiere instalar
ningún módulo en Odoo: usa la conexión estándar con clave API.

.. contents:: Contenido
   :local:
   :depth: 1

Qué hace
========

* **Paso 1 - Convertir imágenes:** transforma fotos PNG, JPG, BMP, GIF o TIFF a WebP, reduce
  su peso y, si se desea, las ajusta a una medida.
* **Paso 2 - Subir a Odoo:** busca cada referencia interna en Odoo y coloca la imagen en el
  producto. Todas sus variantes la muestran.
* **Validar sin subir:** muestra qué productos recibirían una imagen nueva, cuáles se
  reemplazarían y cuáles no existen, sin modificar nada.
* **Reportes:** genera un Excel por proceso y un archivo con las referencias pendientes para
  reintentarlas.
* **Seguro por diseño:** solo se conecta por ``https://``, usa una clave API revocable que no
  se guarda en el equipo y avisa si la clave pertenece a un administrador.

Instalación rápida (Windows)
============================

Todo se instala con un solo archivo: `Instalar.bat <Instalar.bat>`_.

Opción A: descargar y hacer doble clic
--------------------------------------

1. Abra `Instalar.bat <Instalar.bat>`_ en GitHub y haga clic en **Download raw file** (icono
   de descarga, arriba a la derecha del archivo).
2. Haga doble clic en el archivo descargado.
3. Si Windows muestra **Windows protegió su PC**, haga clic en **Más información** y luego en
   **Ejecutar de todas formas**.

Opción B: una línea en PowerShell
---------------------------------

Abra **PowerShell** (no hace falta que sea como administrador) y pegue:

.. code-block:: powershell

   irm https://raw.githubusercontent.com/xxMichaelSilvaxx/carga-imagenes-odoo/main/Instalar.bat -OutFile "$env:TEMP\Instalar.bat"; & "$env:TEMP\Instalar.bat"

Qué hace el instalador
----------------------

1. Busca **Python 3.10 o superior**. Si no lo encuentra, ofrece instalar Python 3.12 con
   ``winget`` solo para el usuario actual (no requiere permisos de administrador).
2. Descarga la última versión del aplicativo desde este repositorio.
3. Copia el aplicativo en ``%LOCALAPPDATA%\CargaImagenesOdoo\app``.
4. Abre la ventana **Preparando el aplicativo** y descarga los componentes necesarios
   (Pillow, requests, openpyxl y sv-ttk) en un entorno propio del aplicativo. El Python
   del equipo no se modifica.
5. Crea en el escritorio el acceso directo **Carga de imágenes a Odoo**, con su icono, y abre
   el aplicativo.

Requisitos
----------

* Windows 10 u 11 con conexión a internet durante la instalación.
* Odoo **19** o superior, accesible por ``https://``.
* Un usuario de Odoo dedicado a la carga, con el permiso **Productos: Crear**, y su **clave
  API**. El `manual <Manual_aplicativo.rst>`_ explica cómo prepararlo.

Actualizar y desinstalar
========================

* **Actualizar:** vuelva a ejecutar ``Instalar.bat``. Descarga la última versión, conserva los
  componentes ya instalados y solo añade los que falten.
* **Desinstalar:** borre la carpeta ``%LOCALAPPDATA%\CargaImagenesOdoo`` y el acceso directo
  del escritorio. La configuración, los reportes y los registros están en
  ``Documentos\CargaImagenesOdoo``; bórrela también si ya no los necesita.

Uso
===

1. Abra **Carga de imágenes a Odoo** desde el escritorio.
2. En **1. Convertir imágenes**, elija la carpeta de fotos y la de destino, y haga clic en
   **Convertir imágenes**.
3. En **2. Subir a Odoo**, complete la URL, la base de datos (si aplica), el usuario y la
   clave API, y haga clic en **Probar conexión**.
4. Haga clic en **Validar sin subir**, revise el resumen y luego haga clic en **Subir
   imágenes**.
5. Revise el reporte de Excel y, si hay pendientes, reintente con el archivo
   ``subida_pendientes_<fecha>.txt``.

El nombre de cada foto, sin extensión, debe ser la referencia interna del producto (por
ejemplo ``ref_0244.webp``). El paso a paso completo, los estados, las alertas y las preguntas
frecuentes están en el `manual del aplicativo <Manual_aplicativo.rst>`_.

Para desarrolladores
====================

Ejecutar desde el código fuente
-------------------------------

En Windows, Linux o macOS con Python 3.10 o superior:

.. code-block:: bash

   git clone https://github.com/xxMichaelSilvaxx/carga-imagenes-odoo.git
   cd carga-imagenes-odoo/codigo_fuente_aplicativo
   python carga_imagenes.py

Si faltan componentes, el aplicativo crea su propio ``.venv`` dentro de
``codigo_fuente_aplicativo``, los instala y se vuelve a abrir desde ese entorno. Si se
ejecuta dentro de un entorno virtual ya activo, los instala en ese entorno. El detalle de la
instalación queda en ``Documentos/CargaImagenesOdoo/logs/instalacion.log``.

Generar el ejecutable
---------------------

En Windows, desde PowerShell en ``codigo_fuente_aplicativo``:

.. code-block:: powershell

   powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

El resultado, ``dist\CargaImagenesOdoo.exe``, es un único archivo con el icono del aplicativo
que no requiere Python. Se recomienda publicarlo como *release* de GitHub en lugar de
guardarlo en el repositorio.

Estructura del repositorio
--------------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Archivo
     - Contenido
   * - ``Instalar.bat``
     - Instalador de un solo archivo para Windows.
   * - ``Manual_aplicativo.rst``
     - Manual funcional completo para el usuario final.
   * - ``codigo_fuente_aplicativo/carga_imagenes.py``
     - Punto de entrada; verifica e instala los componentes antes de abrir la ventana.
   * - ``codigo_fuente_aplicativo/installer.py``
     - Instalación de componentes, entorno propio y acceso directo.
   * - ``codigo_fuente_aplicativo/gui.py``
     - Interfaz gráfica.
   * - ``codigo_fuente_aplicativo/converter.py``
     - Conversión a WebP en paralelo.
   * - ``codigo_fuente_aplicativo/uploader.py``
     - Emparejado de referencias y subida a Odoo.
   * - ``codigo_fuente_aplicativo/odoo_client.py``
     - Conexión JSON-2 con Odoo 19 mediante clave API.
   * - ``codigo_fuente_aplicativo/common.py``
     - Utilidades compartidas, registros y reportes.
   * - ``codigo_fuente_aplicativo/build_exe.ps1``
     - Generación del ejecutable con PyInstaller.
   * - ``codigo_fuente_aplicativo/icon.ico`` / ``icon.png``
     - Icono del aplicativo.

Autor
=====

Nodosys.
