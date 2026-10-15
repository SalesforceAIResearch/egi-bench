from simple_salesforce import Salesforce
import ast
import os, re, pandas as pd
from tqdm import tqdm
from typing import Dict, List
from dotenv import load_dotenv


DATA_DIR = "../data"
CURRENT_SCHEMA_FILE = f"{DATA_DIR}/current_schema.json"
FULL_SCHEMA_FILE = f"{DATA_DIR}/training_org_non_null_full_schema.json"
METADATA_FILE = f"{DATA_DIR}/training_org_full_object_metadata_superset.jsonl"
    


class SalesforceConnector:
    def __init__(self, auth=None, schema_file=FULL_SCHEMA_FILE, org_type="b2b"):
        
        assert org_type in ["b2b", "b2c", "original"], "Invalid organization type"
        if not auth:
            auth = self.sf_auth(org_type)
        if auth.get("username"):
            self.sf = Salesforce(username=auth["username"], password=auth["password"], security_token=auth["security_token"])
        else:
            self.sf = Salesforce(instance_url=auth["instance_url"], session_id=auth["session_id"])
        
    def preprocess_query(self, query: str) -> str:
        # remove tags if present
        pattern1 = f'```(?:sql|SQL|soql|SOQL)?([\S\s]+?)```'
        pattern2 = f'```([\S\s]+?)```'
        matches = re.findall(pattern1, query, re.DOTALL) + re.findall(pattern2, query, re.DOTALL)
        if len(matches) > 0:
            query = " ".join(matches[0].split())
            
        return query

    def _result_to_list(self, result_df: pd.DataFrame, field: str = "Name") -> List[str]:
        return result_df[field].tolist()
        
    def run_query(self, query, return_df: bool = False):
        is_sosl = False
        if query.startswith("FIND"):
            is_sosl = True
        try:
            if not is_sosl:
                query = self.preprocess_query(query)
                result = self.sf.query_all(query)
            else:
                result = self.sf.search(query)
        except Exception as e:
            e = str(e)
            e = ast.literal_eval(e.split("Response content:")[1].strip())[0]
            err = f"{e['errorCode']}: {e['message']}"
            return err, 0
        
        if not is_sosl:
            result_data = result["records"]
        else:
            result_data = result["searchRecords"]
        if len(result_data) == 0:
            return [], 1
        keys = result_data[0].keys()

        for row in result_data:
            if "attributes" in row:
                del row["attributes"]

        all_none_keys = [key for key in keys if all([record[key] is None for record in result_data])]
        new_data = [{k: v for k, v in record.items() if k not in all_none_keys} for record in result_data]
        if return_df:
            return pd.DataFrame(new_data), 1
        return new_data, 1
    
    
    @staticmethod
    def sf_auth(org_type: str):
        auth = dict()
        print(f"Using {org_type} Salesforce credentials")
        if org_type == "b2b":
            if os.environ.get("SALESFORCE_B2B_SECURITY_TOKEN"):
             
                auth = {
                    "username" : os.environ["SALESFORCE_B2B_USERNAME"],
                    "password" : os.environ["SALESFORCE_B2B_PASSWORD"],
                    "security_token" : os.environ["SALESFORCE_B2B_SECURITY_TOKEN"]
                }
                return auth
        elif org_type == "b2c":
            if os.environ.get("SALESFORCE_B2C_SECURITY_TOKEN"):
                auth = {
                    "username" : os.environ["SALESFORCE_B2C_USERNAME"],
                    "password" : os.environ["SALESFORCE_B2C_PASSWORD"],
                    "security_token" : os.environ["SALESFORCE_B2C_SECURITY_TOKEN"]
                }
                return auth
        elif org_type == "original":
            print("Using original Salesforce credentials")
            # Fall back to the public sandbox credentials from the original CRMArena repo
            auth = {
                "username": os.environ.get("SALESFORCE_USERNAME") or "kh.huang+00dws000004urq4@salesforce.com",
                "password": os.environ.get("SALESFORCE_PASSWORD") or "crmarenatest0",
                "security_token": os.environ.get("SALESFORCE_SECURITY_TOKEN") or "ugvBSBv0ArI7dayfqUY0wMGu",
            }
            return auth
        raise ValueError("No Salesforce credentials found in environment variables!")
    
if __name__ == "__main__":
    load_dotenv()
    sf = SalesforceConnector()
    q = """
        SELECT Id, Subject, Status, Priority, Description
        FROM Case
        WHERE Account.Name = 'Acme' AND (Owner.FirstName = 'Edward' OR Owner.LastName = 'Edward')
    """
    op, s = sf.run_query(q)
    if s == 0:
        err = ast.literal_eval(op.split("Response content:")[1].strip())[0]
        print(f"Error: {err['errorCode']} - {err['message']}")
    else:
        print("Query results:")
        print(op)
        print(f"Status: {s}")
