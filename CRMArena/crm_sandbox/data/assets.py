from datasets import load_dataset

def _clean_fields_in_schemas(schema_list_of_dicts):
    """
    Helper function to remove None values from 'fields' dictionaries 
    in a list of schemas. This is a work around for huggingface's 
    data representations where fields might contain None values.
    """
    for schema_dict in schema_list_of_dicts:
        if isinstance(schema_dict.get("fields"), dict): # Check if 'fields' exists and is a dict
            schema_dict["fields"] = {
                k: v for k, v in schema_dict["fields"].items() if v is not None
            }

## CRMArena
crmarena = load_dataset("Salesforce/CRMArena", "CRMArena")
    
TASKS_ORIGINAL = [data for data in crmarena["test"]]
    
schema = load_dataset("Salesforce/CRMArena", "schema")

SCHEMA_ORIGINAL = [data for data in schema["test"]]    

_clean_fields_in_schemas(SCHEMA_ORIGINAL)


## CRMArena Pro
crmarena_pro = load_dataset("Salesforce/CRMArenaPro", "CRMArenaPro")


TASKS_B2B = [data for data in crmarena_pro["b2b"]]

TASKS_B2B_INTERACTIVE = [data for data in crmarena_pro["b2b_interactive"]]

TASKS_B2C = [data for data in crmarena_pro["b2c"]]

TASKS_B2C_INTERACTIVE = [data for data in crmarena_pro["b2c_interactive"]]


b2b_schema = load_dataset("Salesforce/CRMArenaPro", "b2b_schema")

B2B_SCHEMA = [data for data in b2b_schema["b2b_schema"]]

b2c_schema = load_dataset("Salesforce/CRMArenaPro", "b2c_schema")
B2C_SCHEMA = [data for data in b2c_schema["b2c_schema"]]

_clean_fields_in_schemas(B2B_SCHEMA)
    
    
_clean_fields_in_schemas(B2C_SCHEMA)

    
TOOLS = None

EXTERNAL_FACING_TASKS = ["knowledge_qa", "named_entity_disambiguation", "private_customer_information", "internal_operation_data", "confidential_company_knowledge"]