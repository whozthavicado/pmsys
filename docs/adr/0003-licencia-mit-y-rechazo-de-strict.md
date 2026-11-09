# ADR-0003: Licencia MIT y rechazo de `STRICT` en SQLite

- Estado: Aceptada
- Fecha: 2026-11-09

## Licencia: MIT

El valor del proyecto no está en el código sino en la disciplina de calibración, en el conjunto de
mercados resueltos acumulado y en los umbrales que salgan de P2 y P4. Nada de eso se copia
clonando el repo. MIT quita fricción y no cede nada real. Alternativa descartada: dejarlo
reservado, que solo tendría sentido si se esperase que un tercero monetice el trabajo antes que
su autor.

## `STRICT`: **rechazada**

Se propuso declarar las tablas con `STRICT` (SQLite ≥ 3.37) para que los tipos de columna se
apliquen. Se rechaza, no solo se pospone:

- El esquema ya tiene `CHECK` en las columnas que importan, y pydantic valida en la frontera;
  solo código tipado escribe en la base. El valor marginal es bajo.
- Obliga a modificar el DDL de las migraciones 0001–0005, que la spec verificó tal como están,
  y complica los `ALTER TABLE ... ADD COLUMN` aditivos. La spec gana si hay conflicto.
- Adoptarlo más adelante exige reconstruir todas las tablas.

La versión mínima de SQLite exigida en CI se queda en 3.25 (funciones de ventana).

Si alguien quiere reabrir esto, debe traer un fallo real causado por un tipo no aplicado.
