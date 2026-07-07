from django.db import connections
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import Employee


LEGACY_EMPLOYEE_REFERENCE_ACTIONS = (
    ("chat_chatroommember", "user_id", "delete"),
    ("chat_chatmessage", "sender_id", "delete"),
    ("chat_chatroom", "created_by_id", "set_null"),
    ("payroll_expense", "employee_id", "delete"),
    ("payroll_expense", "paid_by_id", "set_null"),
    ("payroll_salarypayment", "employee_id", "delete"),
    ("payroll_salarypayment", "paid_by_id", "set_null"),
    ("payroll_pmresponsibility", "pm_id", "delete"),
    ("payroll_pmsalaryshare", "pm_id", "delete"),
    ("payroll_employeesalary", "employee_id", "delete"),
    ("payroll_employeesalary", "paid_by_id", "set_null"),
)


@receiver(pre_delete, sender=Employee)
def cleanup_legacy_employee_references(sender, instance, using, **kwargs):
    connection = connections[using]
    quote_name = connection.ops.quote_name

    with connection.cursor() as cursor:
        existing_tables = set(connection.introspection.table_names(cursor))
        table_columns = {}

        for table_name, column_name, action in LEGACY_EMPLOYEE_REFERENCE_ACTIONS:
            if table_name not in existing_tables:
                continue

            columns = table_columns.get(table_name)
            if columns is None:
                description = connection.introspection.get_table_description(cursor, table_name)
                columns = {column.name for column in description}
                table_columns[table_name] = columns

            if column_name not in columns:
                continue

            table_sql = quote_name(table_name)
            column_sql = quote_name(column_name)

            if action == "delete":
                cursor.execute(
                    f"DELETE FROM {table_sql} WHERE {column_sql} = %s",
                    [instance.pk],
                )
            elif action == "set_null":
                cursor.execute(
                    f"UPDATE {table_sql} SET {column_sql} = NULL WHERE {column_sql} = %s",
                    [instance.pk],
                )
