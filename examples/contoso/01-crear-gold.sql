/*
  Capa Gold de prueba sobre Contoso (datos públicos de ejemplo).

  Funciona con las dos versiones de Contoso:
    - ContosoRetailDW (Microsoft, 2010): tablas dbo.FactSales, DimStore, DimProduct...
    - Contoso V2 (SQLBI): tablas Sales, Store, Product (esquema Data o dbo).

  Ejecutar conectado a la base Contoso restaurada:
      sqlcmd -S localhost -E -C -f 65001 -d ContosoRetailDW -i examples\contoso\01-crear-gold.sql
  (-f 65001: leer el fichero como UTF-8; sin él los acentos se guardan mal)

  Crea el esquema `gold` con dos tablas agregadas por mes, documentadas con
  MS_Description para que `sofibot schema` las describa. Se puede volver a ejecutar:
  borra y recrea las tablas. Importes en USD.
*/
SET NOCOUNT ON;

IF SCHEMA_ID(N'gold') IS NULL EXEC (N'CREATE SCHEMA gold');
DROP TABLE IF EXISTS gold.month_store, gold.month_product;

DECLARE @sql nvarchar(max);
DECLARE @v2 sysname = (SELECT TOP (1) SCHEMA_NAME(schema_id) FROM sys.tables
                       WHERE name = N'Sales' AND SCHEMA_NAME(schema_id) <> N'gold');

IF OBJECT_ID(N'dbo.FactSales', N'U') IS NOT NULL
BEGIN
    PRINT N'Origen: ContosoRetailDW (dbo.FactSales)';
    SET @sql = N'
WITH m AS (
    SELECT DATEFROMPARTS(YEAR(DateKey), MONTH(DateKey), 1) AS month, StoreKey,
           SUM(SalesAmount) AS sales, SUM(TotalCost) AS cost, SUM(SalesQuantity) AS quantity, COUNT(*) AS sales_lines
    FROM dbo.FactSales
    GROUP BY DATEFROMPARTS(YEAR(DateKey), MONTH(DateKey), 1), StoreKey)
SELECT m.month, m.StoreKey AS store_key,
       CAST(st.StoreName AS nvarchar(100)) AS store_name, CAST(g.RegionCountryName AS nvarchar(60)) AS country,
       CAST(m.sales AS decimal(19,2)) AS sales_usd, CAST(m.cost AS decimal(19,2)) AS cost_usd,
       CAST(m.sales - m.cost AS decimal(19,2)) AS gross_profit_usd,
       CAST(m.quantity AS int) AS quantity, m.sales_lines
INTO gold.month_store
FROM m
LEFT JOIN dbo.DimStore st ON st.StoreKey = m.StoreKey
LEFT JOIN dbo.DimGeography g ON g.GeographyKey = st.GeographyKey;

WITH m AS (
    SELECT DATEFROMPARTS(YEAR(DateKey), MONTH(DateKey), 1) AS month, ProductKey,
           SUM(SalesAmount) AS sales, SUM(TotalCost) AS cost, SUM(SalesQuantity) AS quantity, COUNT(*) AS sales_lines
    FROM dbo.FactSales
    GROUP BY DATEFROMPARTS(YEAR(DateKey), MONTH(DateKey), 1), ProductKey)
SELECT m.month, m.ProductKey AS product_key,
       CAST(p.ProductName AS nvarchar(200)) AS product_name, CAST(p.BrandName AS nvarchar(60)) AS brand,
       CAST(c.ProductCategoryName AS nvarchar(60)) AS category, CAST(sc.ProductSubcategoryName AS nvarchar(60)) AS subcategory,
       CAST(m.sales AS decimal(19,2)) AS sales_usd, CAST(m.cost AS decimal(19,2)) AS cost_usd,
       CAST(m.sales - m.cost AS decimal(19,2)) AS gross_profit_usd,
       CAST(m.quantity AS int) AS quantity, m.sales_lines
INTO gold.month_product
FROM m
LEFT JOIN dbo.DimProduct p ON p.ProductKey = m.ProductKey
LEFT JOIN dbo.DimProductSubcategory sc ON sc.ProductSubcategoryKey = p.ProductSubcategoryKey
LEFT JOIN dbo.DimProductCategory c ON c.ProductCategoryKey = sc.ProductCategoryKey;';
END
ELSE IF @v2 IS NOT NULL
BEGIN
    PRINT N'Origen: Contoso V2 (' + @v2 + N'.Sales)';
    -- Importes en USD = cantidad * precio / tipo de cambio, como en sofibot-project.
    SET @sql = REPLACE(N'
WITH m AS (
    SELECT DATEFROMPARTS(YEAR(OrderDate), MONTH(OrderDate), 1) AS month, StoreKey,
           SUM(Quantity * NetPrice / ExchangeRate) AS sales, SUM(Quantity * UnitCost / ExchangeRate) AS cost,
           SUM(Quantity) AS quantity, COUNT(*) AS sales_lines
    FROM {src}.Sales
    GROUP BY DATEFROMPARTS(YEAR(OrderDate), MONTH(OrderDate), 1), StoreKey)
SELECT m.month, m.StoreKey AS store_key,
       CAST(st.Description AS nvarchar(100)) AS store_name, CAST(st.CountryName AS nvarchar(60)) AS country,
       CAST(m.sales AS decimal(19,2)) AS sales_usd, CAST(m.cost AS decimal(19,2)) AS cost_usd,
       CAST(m.sales - m.cost AS decimal(19,2)) AS gross_profit_usd,
       CAST(m.quantity AS int) AS quantity, m.sales_lines
INTO gold.month_store
FROM m LEFT JOIN {src}.Store st ON st.StoreKey = m.StoreKey;

WITH m AS (
    SELECT DATEFROMPARTS(YEAR(OrderDate), MONTH(OrderDate), 1) AS month, ProductKey,
           SUM(Quantity * NetPrice / ExchangeRate) AS sales, SUM(Quantity * UnitCost / ExchangeRate) AS cost,
           SUM(Quantity) AS quantity, COUNT(*) AS sales_lines
    FROM {src}.Sales
    GROUP BY DATEFROMPARTS(YEAR(OrderDate), MONTH(OrderDate), 1), ProductKey)
SELECT m.month, m.ProductKey AS product_key,
       CAST(p.ProductName AS nvarchar(200)) AS product_name, CAST(p.Brand AS nvarchar(60)) AS brand,
       CAST(p.CategoryName AS nvarchar(60)) AS category, CAST(p.SubCategoryName AS nvarchar(60)) AS subcategory,
       CAST(m.sales AS decimal(19,2)) AS sales_usd, CAST(m.cost AS decimal(19,2)) AS cost_usd,
       CAST(m.sales - m.cost AS decimal(19,2)) AS gross_profit_usd,
       CAST(m.quantity AS int) AS quantity, m.sales_lines
INTO gold.month_product
FROM m LEFT JOIN {src}.Product p ON p.ProductKey = m.ProductKey;', N'{src}', QUOTENAME(@v2));
END
ELSE
    THROW 50001, 'No encuentro ni dbo.FactSales (ContosoRetailDW) ni Sales (Contoso V2). ¿Estás conectado a la base restaurada?', 1;

EXEC (@sql);
CREATE CLUSTERED INDEX ix_month_store ON gold.month_store (month, store_key);
CREATE CLUSTERED INDEX ix_month_product ON gold.month_product (month, product_key);

-- Documentación de tablas y columnas (la recoge `sofibot schema`).
DECLARE @docs TABLE (tbl sysname, col sysname NULL, txt nvarchar(500));
INSERT @docs VALUES
 (N'month_store', NULL, N'Ventas por mes y tienda. Una fila por month y store_key.'),
 (N'month_store', N'month', N'Primer día del mes natural.'),
 (N'month_store', N'store_key', N'Identificador de tienda. NULL = tienda desconocida.'),
 (N'month_store', N'store_name', N'Nombre de la tienda.'),
 (N'month_store', N'country', N'País de la tienda.'),
 (N'month_store', N'sales_usd', N'Venta neta en USD.'),
 (N'month_store', N'cost_usd', N'Coste en USD.'),
 (N'month_store', N'gross_profit_usd', N'sales_usd - cost_usd. Margen % = suma de gross_profit_usd / suma de sales_usd.'),
 (N'month_store', N'quantity', N'Unidades vendidas.'),
 (N'month_store', N'sales_lines', N'Líneas de venta.'),
 (N'month_product', NULL, N'Ventas por mes y producto. Una fila por month y product_key. Mismas ventas que month_store: no sumar ambas tablas.'),
 (N'month_product', N'month', N'Primer día del mes natural.'),
 (N'month_product', N'product_key', N'Identificador de producto.'),
 (N'month_product', N'product_name', N'Nombre del producto.'),
 (N'month_product', N'brand', N'Marca.'),
 (N'month_product', N'category', N'Categoría.'),
 (N'month_product', N'subcategory', N'Subcategoría.'),
 (N'month_product', N'sales_usd', N'Venta neta en USD.'),
 (N'month_product', N'cost_usd', N'Coste en USD.'),
 (N'month_product', N'gross_profit_usd', N'sales_usd - cost_usd.'),
 (N'month_product', N'quantity', N'Unidades vendidas.'),
 (N'month_product', N'sales_lines', N'Líneas de venta.');

DECLARE @tbl sysname, @col sysname, @txt nvarchar(500);
DECLARE docs CURSOR LOCAL FAST_FORWARD FOR SELECT tbl, col, txt FROM @docs;
OPEN docs;
FETCH NEXT FROM docs INTO @tbl, @col, @txt;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF @col IS NULL
        EXEC sp_addextendedproperty N'MS_Description', @txt, N'SCHEMA', N'gold', N'TABLE', @tbl;
    ELSE
        EXEC sp_addextendedproperty N'MS_Description', @txt, N'SCHEMA', N'gold', N'TABLE', @tbl, N'COLUMN', @col;
    FETCH NEXT FROM docs INTO @tbl, @col, @txt;
END;
CLOSE docs;
DEALLOCATE docs;

PRINT N'Gold de Contoso creada: gold.month_store y gold.month_product.';
