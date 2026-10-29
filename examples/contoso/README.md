# Ejemplo: Contoso

Datos públicos de ejemplo (ContosoRetailDW de Microsoft o Contoso V2 de SQLBI) para probar Sofibot sin datos reales.

| Fichero | Qué hace |
|---|---|
| `01-crear-gold.sql` | Crea `gold.month_store` y `gold.month_product` a partir de la base Contoso restaurada |
| `reports/contoso-ventas-tiendas/` | Informe completo: KPIs, gráficos, tabla interactiva y Excel descargable |
| `reports/contoso-productos-excel/` | Informe que solo entrega un Excel con varias hojas |
| `refrescar.ps1` | Pipeline de prueba: recrea la capa gold y pide al portal que regenere los informes |

Para usarlos, copia las carpetas de `reports/` a la carpeta `reports/` del proyecto y
ejecuta `sofibot build --all`. El paso a paso completo está en `GUIA-DATASOFI.md`.
