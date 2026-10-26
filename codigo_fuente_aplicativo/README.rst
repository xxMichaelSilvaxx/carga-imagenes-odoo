=====================================
Carga de imágenes de productos a Odoo
=====================================

DATOS DEL SISTEMA / MÓDULO
==========================

:Nombre: Carga de imágenes a Odoo (``CargaImagenesOdoo.exe``). Trabaja con Odoo estándar:
         no requiere instalar ningún módulo en Odoo.
:Usuarios: personal de catálogo, bodega o comercial encargado de las fotos de productos.
:Objetivo: convertir las fotos de productos a un formato liviano (WebP) y subirlas a los
           productos de Odoo, identificándolos por su referencia interna, de forma segura.

1. INTRODUCCIÓN Y ALCANCE
=========================

El aplicativo reúne dos tareas en una sola ventana:

* **Paso 1 - Convertir imágenes:** transforma fotos PNG, JPG, BMP, GIF o TIFF a WebP,
  reduce su peso y, si se desea, las ajusta a una medida.
* **Paso 2 - Subir a Odoo:** busca cada referencia interna en Odoo y coloca la imagen en el
  producto. Todas las variantes de ese producto (por ejemplo, cada talla) la muestran.

Beneficios:

* No se necesita entrar a Odoo producto por producto.
* Muestra el porcentaje, la velocidad, el tiempo transcurrido y el tiempo restante, y un
  resumen con colores de cuántas imágenes quedaron en cada estado.
* Distingue las imágenes **nuevas** de las que **reemplazaron** una existente.
* Genera un reporte en Excel (``.xlsx``) donde las referencias se conservan tal cual, sin
  perder ceros iniciales (``0201``) ni convertirse en números científicos.
* Las referencias que terminan en un sufijo como ``_PROMOCIONALES`` se tratan como la misma
  referencia: ``ref_0244`` y ``ref_0244_PROMOCIONALES`` reciben la misma foto.

Seguridad:

* Solo se conecta por ``https://``; las direcciones ``http://`` se rechazan (salvo un
  servidor de pruebas en el mismo equipo).
* No usa la contraseña del usuario: usa una **clave API** que vence y se puede revocar.
* La clave no se guarda en el equipo ni aparece en los registros.
* Al probar la conexión, el aplicativo avisa si la clave pertenece a un **administrador**.
* La clave puede hacer en Odoo lo mismo que su usuario. Por eso debe pertenecer a un
  **usuario dedicado** que solo tenga el permiso **Productos: Crear**: si la clave se filtra,
  solo se podrían editar o crear productos, no ventas, compras, contabilidad, inventario ni
  usuarios. Revoque la clave al terminar cada campaña de carga.

Límites:

* El nombre del archivo, sin la extensión, debe ser la referencia interna del producto
  (por ejemplo, ``ref_0244.webp``).
* Solo actualiza la imagen principal del producto. No crea productos ni cambia otros datos.
* Los productos archivados o de compañías no asignadas al usuario no se actualizan.
* Requiere Odoo 19 (usa la conexión JSON-2 con clave API, que no existe en versiones
  anteriores).

2. ROLES Y MATRIZ DE PERMISOS
=============================

.. list-table::
   :header-rows: 1
   :widths: 22 39 39

   * - Perfil
     - Puede hacer
     - No puede hacer
   * - Operador del aplicativo (persona en el computador)
     - Convertir imágenes, validar y subir con la clave API entregada, revisar reportes.
     - Usar la clave para cualquier otra tarea en Odoo.
   * - Usuario de carga (permiso "Productos: Crear")
     - Ser el dueño de la clave API; subir o reemplazar la imagen principal de productos de
       sus compañías.
     - Modificar ventas, compras, contabilidad, inventario o usuarios.
   * - Usuario de Odoo sin el permiso "Productos: Crear"
     - Nada desde el aplicativo.
     - Subir imágenes: el aplicativo muestra que no tiene permiso para modificar productos.
   * - Administrador de Odoo
     - Crear el usuario de carga, asignar el permiso y revocar claves.
     - No debe entregar una clave de administrador: el aplicativo la aceptará, pero avisará
       del riesgo.

3. PRERREQUISITOS Y REGLAS DE NEGOCIO
=====================================

Antes de empezar, el administrador de Odoo debe entregarle:

* La **URL de Odoo** (por ejemplo ``https://miempresa.odoo.com``).
* El **nombre de la base de datos**, solo si el servidor tiene varias. En Odoo.sh puede
  dejarse vacío.
* El **usuario** (correo) dedicado a la carga y su **clave API**.

Cómo prepara el administrador el usuario dedicado:

1. En **Ajustes > Usuarios y compañías > Usuarios**, cree un usuario interno, por ejemplo
   "Carga de imágenes".
2. Quítele todos los permisos de Ventas, Compras, Inventario, Contabilidad y Administración.
3. En el bloque de datos maestros, en **Productos**, seleccione **Crear**.
4. Inicie sesión con ese usuario, abra **Mi perfil > Seguridad de la cuenta > Nueva clave
   API**, elija una duración corta (por ejemplo 1 mes) y copie la clave.

   [INSERTAR CAPTURA DE PANTALLA: usuario dedicado con el permiso Productos: Crear]

Además necesita:

* La carpeta con las fotos, cuyos nombres sean las referencias internas.
* Opcional: un archivo ``.txt`` con las referencias a procesar, una por línea. Se ignoran
  las líneas en blanco y las que empiezan con ``#``. Si una línea tiene varias columnas
  separadas por coma, punto y coma o tabulación, solo se usa la primera.

Reglas que aplica el aplicativo:

* **Mayúsculas y tildes no importan:** ``REF_0244`` y ``ref_0244`` son la misma referencia.
* **Sufijos equivalentes:** con la casilla "Tratar como la misma referencia las que terminan
  en" marcada, ``ref_0244``, ``ref_0244_PROMOCIONALES``, ``ref_0244-PROMOCIONALES`` y
  ``ref_0244 PROMOCIONALES`` forman un mismo grupo. Puede escribir varios sufijos separados
  por coma (por ejemplo ``PROMOCIONALES, OUTLET``).
* **Qué foto recibe cada producto del grupo:** primero la foto con su nombre exacto; si no
  existe, la de la referencia base (``ref_0244.webp``); si tampoco existe, cualquier foto
  del grupo. El reporte indica cuándo un producto usó la foto de otra referencia.
* **Imágenes existentes:** con "Actualizar las imágenes que ya existen en Odoo" marcada
  (opción por defecto), la foto nueva reemplaza la anterior y el estado es **Actualizada**.
  Si la desmarca, el producto conserva su foto y el estado es **Conservada**.
* **Archivos repetidos:** si existen ``ref_0244.png`` y ``ref_0244.webp`` en la misma
  carpeta, se usa el ``.webp``.
* **Límites de imagen:** máximo 20 MB por archivo y 50 megapíxeles. Las imágenes más grandes
  deben pasar antes por el paso 1.

4. GUÍA PASO A PASO (FLUJO PRINCIPAL)
=====================================

4.1 Abrir el aplicativo
-----------------------

1. Haga doble clic en ``CargaImagenesOdoo.exe``. La ventana se abre maximizada: a la
   izquierda están las pestañas "1. Convertir imágenes" y "2. Subir a Odoo"; a la derecha,
   el **Progreso**, el **Resumen** por estados, los **Resultados** y el **Registro**.

   [INSERTAR CAPTURA DE PANTALLA: ventana principal con formularios a la izquierda y progreso a la derecha]

4.2 Paso 1: convertir imágenes a WebP
-------------------------------------

1. Abra la pestaña **1. Convertir imágenes**.
2. En "Carpeta con las imágenes originales", haga clic en **Examinar...** y seleccione la
   carpeta con las fotos.
3. En "Carpeta donde guardar los .webp", seleccione una carpeta de destino. Puede ser una
   carpeta nueva; los originales no se modifican.
4. Marque **Incluir subcarpetas** solo si las fotos están repartidas en subcarpetas.
5. En "¿Qué referencias procesar?", elija **Todas las imágenes de la carpeta** o **Solo las
   referencias de un archivo .txt** y seleccione el archivo. Debajo aparece cuántas
   referencias contiene.

   [INSERTAR CAPTURA DE PANTALLA: bloque de referencias con el archivo .txt seleccionado]

6. Revise la casilla de sufijos equivalentes y el texto ``PROMOCIONALES``.
7. En "Tamaño", seleccione:

   * **Máximo 1920 px sin deformar (recomendado):** reduce solo las fotos más grandes.
   * **Cuadrado 1024 x 1024 con fondo transparente:** todas quedan cuadradas y centradas.
   * **Mantener el tamaño original.**
   * **Personalizado:** indique ancho, alto y la forma de ajuste.

8. Deje la **Calidad** en 90, salvo indicación contraria. Si un ``.webp`` pesa más que el
   original, el aplicativo baja la calidad hasta 70; si aun así pesa más, copia el original.
9. Marque **Rehacer los .webp que ya existen** solo si quiere volver a generarlos.
10. Haga clic en **Convertir imágenes** y siga el avance en el panel **Progreso**.

    [INSERTAR CAPTURA DE PANTALLA: conversión en curso con porcentaje y tiempo restante]

11. Al terminar aparece un resumen. Haga clic en un recuadro del **Resumen** para ver solo
    las imágenes de ese estado: Convertida, Copiada sin convertir, Ya existía, Error o Sin
    imagen en la carpeta.

    [INSERTAR CAPTURA DE PANTALLA: resumen y resultados de la conversión]

4.3 Paso 2: conectar con Odoo
-----------------------------

1. Abra la pestaña **2. Subir a Odoo**.
2. Complete **URL de Odoo** (por ejemplo ``https://miempresa.odoo.com``).
3. Complete **Base de datos** solo si se la indicaron; en Odoo.sh déjela vacía.
4. Complete **Usuario (correo)** del usuario de carga. El aplicativo verifica que la clave le
   pertenezca.
5. Pegue la **Clave API**. Use **Mostrar** para revisarla y **¿Cómo obtenerla?** para ver
   los pasos en Odoo.
6. Haga clic en **Probar conexión**. Si es correcta, aparece en verde el nombre del usuario,
   la versión de Odoo, la base y "HTTPS cifrado".

   [INSERTAR CAPTURA DE PANTALLA: bloque de conexión con el mensaje verde de conexión correcta]

La URL, la base, el usuario y las carpetas se recuerdan para la próxima vez. La clave API no
se guarda: debe pegarla cada vez que abra el aplicativo.

4.4 Paso 2: validar sin subir
-----------------------------

1. En "Carpeta con las imágenes a subir", seleccione la carpeta de ``.webp``, o haga clic en
   **Usar la carpeta de .webp del paso 1**.
2. Elija las referencias a procesar (todas o un archivo ``.txt``).
3. Revise la casilla de sufijos equivalentes.
4. Decida si deja marcada **Actualizar las imágenes que ya existen en Odoo**.
5. Haga clic en **Validar sin subir**. El aplicativo lee los productos de Odoo y muestra qué
   pasaría, sin modificar nada: **Se agregaría**, **Se actualizaría**, **Conservada**, **No
   existe en Odoo** o **Sin imagen en la carpeta**.

   [INSERTAR CAPTURA DE PANTALLA: resultados de la validación con los recuadros de resumen]

6. Corrija los nombres de archivo o el ``.txt`` si hay referencias con "No existe en Odoo"
   o "Sin imagen en la carpeta".

4.5 Paso 2: subir las imágenes
------------------------------

1. Ajuste **Subidas simultáneas**. El valor 4 es adecuado para Odoo.sh. Bájelo a 2 si
   aparecen avisos de "demasiadas solicitudes" y súbalo como máximo a 8 con buena conexión.
2. Haga clic en **Subir imágenes**.
3. Lea el mensaje de confirmación (carpeta, servidor, cantidad de referencias y si se
   actualizarán imágenes existentes) y haga clic en **Sí**.

   [INSERTAR CAPTURA DE PANTALLA: mensaje de confirmación antes de subir]

4. Siga el avance en **Progreso**: porcentaje, imágenes por segundo, tiempo transcurrido y
   tiempo restante. Los recuadros del **Resumen** se actualizan en vivo.

   [INSERTAR CAPTURA DE PANTALLA: subida en curso con porcentaje y recuadros de resumen]

5. Si necesita detenerse, haga clic en **Cancelar** y confirme. Lo ya subido se conserva; el
   resto queda como "Cancelada" en el archivo de pendientes.
6. Al finalizar, revise el resumen y haga clic en **Abrir reporte en Excel** para guardar o
   compartir el detalle. El libro tiene la hoja **Resultados** (con filtros) y la hoja
   **Resumen** (cantidad por estado).

   [INSERTAR CAPTURA DE PANTALLA: reporte de Excel con la hoja Resultados]

4.6 Reintentar las referencias pendientes
-----------------------------------------

1. Haga clic en **Carpeta de reportes**.
2. Abra ``subida_pendientes_<fecha>.txt``. Contiene solo las referencias con error, sin
   imagen o canceladas.
3. Corrija la causa (foto faltante o dañada, conexión, etc.).
4. En el paso 2, elija **Solo las referencias de un archivo .txt**, seleccione ese archivo y
   vuelva a subir.

   [INSERTAR CAPTURA DE PANTALLA: carpeta de reportes con el archivo de pendientes]

4.7 Dónde quedan los reportes y registros
-----------------------------------------

En la carpeta *Documentos\\CargaImagenesOdoo* del usuario de Windows:

* ``reportes``: un ``.xlsx`` por cada proceso y el ``.txt`` de pendientes.
* ``logs``: un registro diario con la conexión, el resumen y **una línea por cada imagen**
  con su estado, útil para auditoría y soporte.

Estados de la subida:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Estado
     - Significado
   * - Nueva
     - El producto no tenía imagen y ahora la tiene.
   * - Actualizada
     - El producto tenía imagen y fue reemplazada por la nueva.
   * - Se agregaría / Se actualizaría
     - Resultado de "Validar sin subir": lo que pasará al ejecutar la carga.
   * - Conservada
     - El producto ya tenía imagen y se mantuvo, porque no se marcó "Actualizar las imágenes
       que ya existen en Odoo".
   * - No existe en Odoo
     - Ningún producto activo de sus compañías tiene esa referencia interna.
   * - Sin imagen en la carpeta
     - El producto existe, pero no hay foto con esa referencia.
   * - Omitida
     - Otra variante del mismo producto ya recibe una foto diferente.
   * - Error
     - No se pudo subir. El detalle indica la causa.
   * - Cancelada
     - El proceso se detuvo antes de llegar a esa imagen.

5. MANEJO DE ALERTAS Y MENSAJES DEL SISTEMA
===========================================

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Mensaje
     - Causa e impacto
     - Qué hacer
   * - Por seguridad solo se permiten direcciones https://
     - Se escribió una dirección ``http://``. No se conecta.
     - Use la dirección con ``https://``.
   * - La clave API no es válida, fue revocada o ya venció
     - La clave se copió mal, se eliminó o pasó su fecha. No se conecta.
     - Pida al administrador una nueva clave.
   * - La clave API pertenece al usuario ..., no a ...
     - El correo escrito no corresponde a la clave.
     - Corrija el correo o use la clave correcta.
   * - El usuario ... no tiene permiso para modificar productos en Odoo / El usuario de la
       clave API no tiene permiso para esta operación
     - El usuario de la clave no tiene el permiso **Productos: Crear**. No se sube nada.
     - Pida al administrador que se lo asigne.
   * - La clave API es de un ADMINISTRADOR
     - La clave entregada da acceso total a Odoo. La carga funciona, pero el riesgo es alto
       si la clave se filtra.
     - Pida una clave de un usuario dedicado y revoque la del administrador.
   * - Escriba el usuario (correo) dueño de la clave API / La clave API no pertenece al
       usuario
     - Con claves de administrador el aplicativo necesita el correo para identificar al
       dueño.
     - Escriba el correo del dueño de la clave.
   * - El servidor tiene varias bases de datos / No existe la base de datos
     - Falta el nombre de la base o está mal escrito.
     - Escriba el nombre exacto de la base.
   * - El servidor tiene Odoo ...; el aplicativo requiere Odoo 19 o superior
     - El servidor es de una versión anterior.
     - Use el aplicativo solo con Odoo 19.
   * - No se pudo conectar con ... / no respondió a tiempo
     - La dirección no existe, no hay internet u Odoo está reiniciando.
     - Revise la URL y la red; el aplicativo reintenta tres veces antes de marcar Error.
   * - No se pudo verificar el certificado de seguridad (HTTPS)
     - La dirección no es la correcta o la fecha y hora del equipo están mal.
     - Corrija la URL y la fecha y hora de Windows.
   * - El servidor redirige a una conexión sin cifrar (http)
     - El servidor no protege la conexión. Se bloquea.
     - Informe al administrador del sistema.
   * - El servidor está limitando las solicitudes
     - Demasiadas subidas a la vez. Las imágenes afectadas quedan con Error.
     - Baje "Subidas simultáneas" a 2 y reintente con el archivo de pendientes.
   * - El archivo no es una imagen válida o está dañado / pesa más de 20 MB / más de 50
       megapíxeles
     - Esa referencia queda con Error.
     - Vuelva a exportar la foto o conviértala en el paso 1.
   * - Estos productos no existen o no están permitidos
     - El producto se archivó o es de otra compañía durante la carga.
     - Revise el producto en Odoo y reintente con el archivo de pendientes.
   * - Esta instalación no soporta WebP
     - El aplicativo está incompleto. No se puede convertir.
     - Solicite una nueva copia de ``CargaImagenesOdoo.exe``.
   * - No se puede escribir en la carpeta de destino
     - No hay permisos o el disco está lleno.
     - Elija otra carpeta, por ejemplo una dentro de Documentos.

6. PREGUNTAS FRECUENTES (FAQ)
=============================

**Si una imagen ya existe en Odoo, ¿se reemplaza?**
  Sí, con la casilla "Actualizar las imágenes que ya existen en Odoo" marcada (por
  defecto). El reporte la muestra como **Actualizada**, y el registro diario guarda una línea
  por cada producto actualizado.

**Tengo ``ref_0244`` y ``ref_0244_PROMOCIONALES``, pero solo una foto. ¿Qué pasa?**
  Con la casilla de sufijos equivalentes marcada, ambos productos reciben esa foto. Si
  existe además ``ref_0244_PROMOCIONALES.webp``, ese producto recibe su propia foto. Para
  tratarlas como referencias independientes, desmarque la casilla.

**¿Qué pasa si se corta el internet a mitad de la carga?**
  Cada imagen se guarda en Odoo por separado: lo subido queda subido. Las afectadas se marcan
  con Error y quedan en ``subida_pendientes_<fecha>.txt`` para reintentarlas.

**¿Qué pasa si alguien obtiene la clave o copia el aplicativo?**
  Podría hacer lo mismo que el usuario de la clave. Por eso debe ser un usuario dedicado con
  solo **Productos: Crear**, nunca un administrador: así el daño posible se limita a
  productos. Avise al administrador para que revoque la clave y genere otra.

**¿Hay que instalar algo en Odoo?**
  No. El aplicativo usa la conexión estándar de Odoo 19 con clave API. Solo se necesita el
  usuario dedicado y su clave.

**¿Por qué Excel ya no cambia mis referencias?**
  El reporte es un libro ``.xlsx`` con todas las celdas en formato texto. Referencias como
  ``0201`` o ``10E5`` se ven exactamente como en Odoo.

Anexo para soporte técnico
==========================

Instalar en un equipo sin el ejecutable
---------------------------------------

1. Descargue el archivo ``Instalar.bat`` del repositorio y haga doble clic en él. Si Windows
   muestra **Windows protegió su PC**, haga clic en **Más información** y luego en
   **Ejecutar de todas formas**.
2. Si el equipo no tiene Python 3.10 o superior, el instalador lo indica y ofrece
   instalarlo. Responda **S** y espere a que termine.
3. El instalador descarga la última versión del aplicativo y la copia en
   *%LOCALAPPDATA%\\CargaImagenesOdoo\\app*.
4. Se abre la ventana **Preparando el aplicativo**, que descarga los componentes
   necesarios. Requiere internet.
5. Al terminar, se crea en el escritorio el acceso directo **Carga de imágenes a Odoo**, con
   el icono del aplicativo, y el aplicativo se abre.

Para actualizar, vuelva a ejecutar ``Instalar.bat``. Si se abre ``carga_imagenes.py``
directamente y faltan componentes, el aplicativo los instala de la misma forma antes de
mostrar la ventana principal. Si la descarga falla, el detalle queda en el registro
``instalacion.log`` de la carpeta ``logs``.

Generar el ejecutable
---------------------

Desde PowerShell, en la carpeta del aplicativo::

    powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

El archivo ``dist\CargaImagenesOdoo.exe`` no requiere instalar Python, lleva el icono del
aplicativo y es el que se entrega al personal.
