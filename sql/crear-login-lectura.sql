/*
  Login de solo lectura para Sofibot.

  Lo ejecuta un administrador de SQL Server (SSMS, VS Code con la extensión mssql o sqlcmd).
  Concede SELECT únicamente sobre el esquema Gold: Sofibot no puede leer otros esquemas
  ni escribir, borrar o modificar nada.

  1. Cambia los cuatro valores de abajo. Contraseña: larga, con letras, números y
     símbolos, pero sin acentos ni ñ (evita problemas de codificación).
  2. Ejecuta el script completo. Se puede volver a ejecutar: actualiza la contraseña
     y vuelve a conceder el permiso. Con sqlcmd, usa -f 65001 para leerlo como UTF-8:
         sqlcmd -S <servidor> -E -f 65001 -i crear-login-lectura.sql
  3. Pon los mismos valores en el fichero .env de Sofibot
     (SQLSERVER_USER, SQLSERVER_PASSWORD, SQLSERVER_DATABASE, SQLSERVER_GOLD_SCHEMA).

  Azure SQL Database no admite logins de servidor desde una base de usuario: allí crea un
  usuario contenido, conectado a la base de datos del warehouse:
      CREATE USER [sofibot_lectura] WITH PASSWORD = N'...';
      GRANT SELECT ON SCHEMA::[gold] TO [sofibot_lectura];
*/
DECLARE @login    sysname       = N'sofibot_lectura';
DECLARE @password nvarchar(128) = N'CAMBIAR-por-una-contrasena-larga';
DECLARE @database sysname       = N'CAMBIAR-nombre-de-la-base-del-warehouse';
DECLARE @schema   sysname       = N'gold';

SET NOCOUNT ON;
BEGIN TRY
    IF @password LIKE N'CAMBIAR%' OR @database LIKE N'CAMBIAR%'
        THROW 50000, 'Cambia @password y @database al principio del script antes de ejecutarlo.', 1;
    IF DB_ID(@database) IS NULL
        THROW 50001, 'La base de datos indicada en @database no existe en este servidor.', 1;

    DECLARE @sql nvarchar(max);

    -- 1. Login de servidor (autenticación de SQL Server, con la política de contraseñas de Windows).
    SET @sql = CASE WHEN SUSER_ID(@login) IS NULL THEN N'CREATE' ELSE N'ALTER' END
        + N' LOGIN ' + QUOTENAME(@login)
        + N' WITH PASSWORD = N' + QUOTENAME(@password, '''')
        + N', DEFAULT_DATABASE = ' + QUOTENAME(@database)
        + N', CHECK_POLICY = ON;';
    EXEC (@sql);

    -- 2. Usuario en la base del warehouse con SELECT solo sobre el esquema Gold.
    SET @sql = N'USE ' + QUOTENAME(@database) + N';
    IF SCHEMA_ID(@schema) IS NULL
        THROW 50002, ''El esquema indicado en @schema no existe en la base de datos.'', 1;
    DECLARE @statement nvarchar(max);
    IF USER_ID(@login) IS NULL
    BEGIN
        SET @statement = N''CREATE USER '' + QUOTENAME(@login) + N'' FOR LOGIN '' + QUOTENAME(@login);
        EXEC (@statement);
    END;
    SET @statement = N''GRANT SELECT ON SCHEMA::'' + QUOTENAME(@schema) + N'' TO '' + QUOTENAME(@login);
    EXEC (@statement);';
    EXEC sp_executesql @sql, N'@login sysname, @schema sysname', @login = @login, @schema = @schema;

    PRINT N'Listo: ' + @login + N' puede leer ' + @database + N'.' + @schema + N' y nada más.';
END TRY
BEGIN CATCH
    PRINT N'ERROR: el script se ha detenido. Corrige lo que indica el mensaje siguiente y vuelve a ejecutarlo (se puede ejecutar varias veces).';
    THROW;
END CATCH;
