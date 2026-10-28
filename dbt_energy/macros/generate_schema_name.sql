{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set default_schema = target.schema -%}
    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    {%- else -%}
        {%- set env_suffix = env_var('DBT_ENV_SUFFIX', target.name) -%}
        energy_{{ custom_schema_name | trim }}_{{ env_suffix }}
    {%- endif -%}
{%- endmacro %}
