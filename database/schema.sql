/* Run this while connected to the database named by MSSQL_DATABASE. */
IF OBJECT_ID(N'dbo.ServiceDefinitions', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.ServiceDefinitions (
        id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        display_name NVARCHAR(255) NOT NULL,
        service_name NVARCHAR(255) NOT NULL UNIQUE,
        enabled BIT NOT NULL CONSTRAINT DF_ServiceDefinitions_enabled DEFAULT 1,
        created_at DATETIME2 NOT NULL CONSTRAINT DF_ServiceDefinitions_created_at DEFAULT SYSUTCDATETIME()
    );
END;

IF OBJECT_ID(N'dbo.ServiceStatusHistory', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.ServiceStatusHistory (
        id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        service_id INT NOT NULL,
        status NVARCHAR(32) NOT NULL,
        startup_type NVARCHAR(64) NULL,
        checked_at DATETIME2 NOT NULL,
        hostname NVARCHAR(255) NOT NULL,
        CONSTRAINT FK_ServiceStatusHistory_ServiceDefinitions FOREIGN KEY (service_id)
            REFERENCES dbo.ServiceDefinitions(id)
    );
    CREATE INDEX IX_ServiceStatusHistory_service_id_checked_at
        ON dbo.ServiceStatusHistory(service_id, checked_at DESC);
    CREATE INDEX IX_ServiceStatusHistory_checked_at ON dbo.ServiceStatusHistory(checked_at DESC);
    CREATE INDEX IX_ServiceStatusHistory_status ON dbo.ServiceStatusHistory(status);
END;
