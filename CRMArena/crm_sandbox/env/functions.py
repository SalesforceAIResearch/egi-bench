import os
from simple_salesforce import Salesforce
from collections import defaultdict
from datetime import datetime
from dateutil.relativedelta import relativedelta


def get_agents_with_max_cases(subset_cases, sf_connector=None):
    """
    Returns a list of agent IDs with the maximum number of cases from the given subset of cases.

    This function counts the number of cases handled by each agent in the provided subset
    and returns a list of agent IDs that have handled the maximum number of cases.

    Parameters:
    - subset_cases (list): A list of case records, where each record is expected to have an 'OwnerId' field
                           representing the agent ID.

    Returns:
    - list: A list of agent IDs (strings) who have handled the maximum number of cases.
            Returns an empty list if no cases are provided.
    - str: An error message if any error occurs during execution.

    Note:
    - If multiple agents have the same maximum number of cases, all of their IDs will be returned.
    - The function assumes that 'OwnerId' in each case record represents the agent ID.
    """
    
    try:
        if not isinstance(subset_cases, list):
            return "Error: Input 'subset_cases' must be a list"

        agent_issue_counts = {}
        for index, record in enumerate(subset_cases):
            if not isinstance(record, dict):
                return f"Error: Item at index {index} in subset_cases is not a dictionary"
            
            if 'OwnerId' not in record:
                return f"Error: 'OwnerId' not found in case record at index {index}"
            
            agent_id = record['OwnerId']
            if not isinstance(agent_id, str):
                return f"Error: 'OwnerId' at index {index} is not a string"
            
            agent_issue_counts[agent_id] = agent_issue_counts.get(agent_id, 0) + 1

        if agent_issue_counts:
            max_count = max(agent_issue_counts.values())
            return [agent for agent, count in agent_issue_counts.items() if count == max_count]
        else:
            return []
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"
    
def get_agents_with_min_cases(subset_cases, sf_connector=None):
    """
    Returns a list of agent IDs with the minimum number of cases from the given subset of cases.

    This function counts the number of cases handled by each agent in the provided subset
    and returns a list of agent IDs that have handled the minimum number of cases.

    Parameters:
    - subset_cases (list): A list of case records, where each record is expected to have an 'OwnerId' field
                           representing the agent ID.

    Returns:
    - list: A list of agent IDs (strings) who have handled the minimum number of cases.
            Returns an empty list if no cases are provided.
    - str: An error message if any error occurs during execution.
    """
    try:
        if not isinstance(subset_cases, list):
            return "Error: Input 'subset_cases' must be a list"

        agent_issue_counts = {}
        for index, record in enumerate(subset_cases):
            if not isinstance(record, dict):
                return f"Error: Item at index {index} in subset_cases is not a dictionary"
            
            if 'OwnerId' not in record:
                return f"Error: 'OwnerId' not found in case record at index {index}"
            
            agent_id = record['OwnerId']
            if not isinstance(agent_id, str):
                return f"Error: 'OwnerId' at index {index} is not a string"
            
            agent_issue_counts[agent_id] = agent_issue_counts.get(agent_id, 0) + 1

        if agent_issue_counts:
            min_count = min(agent_issue_counts.values())
            return [agent for agent, count in agent_issue_counts.items() if count == min_count]
        else:
            return []
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"




def calculate_average_handle_time(cases, sf_connector=None):
    """
    Calculate the average handle time for each agent based on a list of cases.

    This function computes the average time taken by each agent to handle their assigned cases.
    The handle time for a case is calculated as the difference between its closed date and created date.

    Parameters:
    - cases (list): A list of case dictionaries. Each case should have 'CreatedDate', 'ClosedDate', and 'OwnerId' keys.

    Returns:
    - dict: A dictionary where keys are agent IDs (OwnerId) and values are their average handle times in minutes.
    - str: An error message if any error occurs during execution.

    Note:
    - The function assumes that 'CreatedDate' and 'ClosedDate' are strings in the format '%Y-%m-%dT%H:%M:%S.%f%z'.
    - If an agent has no cases or all their cases have invalid dates, they will not be included in the result.
    """
    try:
        if not isinstance(cases, list):
            return "Error: Input 'cases' must be a list"

        agent_handle_times = defaultdict(list)
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                return f"Error: Item at index {index} in cases is not a dictionary"
            
            required_keys = ['CreatedDate', 'ClosedDate', 'OwnerId']
            for key in required_keys:
                if key not in case:
                    return f"Error: '{key}' not found in case record at index {index}"
            
            try:
                created_date = datetime.strptime(case['CreatedDate'], '%Y-%m-%dT%H:%M:%S.%f%z')
                closed_date = datetime.strptime(case['ClosedDate'], '%Y-%m-%dT%H:%M:%S.%f%z')
            except ValueError:
                return f"Error: Invalid date format at index {index}. Expected format: '%Y-%m-%dT%H:%M:%S.%f%z'"
            
            if closed_date < created_date:
                return f"Error: ClosedDate is earlier than CreatedDate at index {index}"
            
            handle_time = (closed_date - created_date).total_seconds() / 60
            agent_handle_times[case['OwnerId']].append(handle_time)
        
        result = {}
        for agent, times in agent_handle_times.items():
            if times:
                result[agent] = sum(times) / len(times)
        
        return result
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"
        


def get_start_date(end_date, period, interval_count, sf_connector=None):
    """
    Calculate the start date based on the end date, period, and interval count.

    This function computes the start date by subtracting a specified time interval
    from the given end date.

    Parameters:
    - end_date (str): The end date in ISO format 'YYYY-MM-DDTHH:MM:SSZ'.
    - period (str): The time period unit ('day', 'week', 'month', or 'quarter').
    - interval_count (int): The number of periods to subtract from the end date.

    Returns:
    - str: The calculated start date in ISO format 'YYYY-MM-DDTHH:MM:SSZ'.
    - str: An error message if any error occurs during execution.

    Note:
    - The function uses relativedelta for accurate date calculations, especially
      for months and quarters which can have varying lengths.
    """
    try:
        if not isinstance(end_date, str):
            return "Error: end_date must be a string"
        if not isinstance(period, str):
            return "Error: period must be a string"
        if not isinstance(interval_count, int):
            return "Error: interval_count must be an integer"
        
        if period not in ['day', 'week', 'month', 'quarter']:
            return "Error: Invalid period. Must be 'day', 'week', 'month', or 'quarter'"
        
        try:
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            return "Error: Invalid end_date format. Expected format: 'YYYY-MM-DDTHH:MM:SSZ'"
        
        if interval_count < 0:
            return "Error: interval_count must be a non-negative integer"
        
        if period == 'week':
            start_date = end_date_obj - relativedelta(weeks=interval_count)
        elif period == 'month':
            start_date = end_date_obj - relativedelta(months=interval_count)
        elif period == 'quarter':
            start_date = end_date_obj - relativedelta(months=3 * interval_count)
        elif period == 'day':
            start_date = end_date_obj - relativedelta(days=interval_count)
        
        return start_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"


def get_period(period_name, year, sf_connector=None):
    """
    Calculate the start and end date based on the period name and year.

    This function determines the start and end dates for a given period (month, quarter, or season)
    and returns them in ISO format.

    Parameters:
    - period_name (str): The name of the period ('January', 'February', ..., 'December', 'Q1', 'Q2', 'Q3', 'Q4', 'Spring', 'Summer', 'Fall', 'Winter').
    - year (int): The year in which the period falls.
    
    Returns:
    - dict: A dictionary with 'start_date' and 'end_date' keys.
    - str: An error message if any error occurs during execution.

    Note:
    - The function uses datetime and relativedelta for accurate date calculations.
    """
    try:
        if not isinstance(period_name, str):
            return "Error: period_name must be a string"
        if not isinstance(year, int):
            return "Error: year must be an integer"

        valid_periods = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December', 'Q1', 'Q2', 'Q3', 'Q4', 'Spring', 'Summer', 'Fall', 'Winter']
        if period_name not in valid_periods:
            return f"Error: Invalid period_name. Must be one of {', '.join(valid_periods)}"

        if year < 1 or year > 9999:
            return "Error: year must be between 1 and 9999"

        if 'Q' in period_name:
            quarter = int(period_name[1])
            start_date = datetime(year, 3 * quarter - 2, 1)
            end_date = start_date + relativedelta(months=3) 
        elif period_name in ['Spring', 'Summer', 'Fall', 'Winter']:
            seasons = {'Spring': 3, 'Summer': 6, 'Fall': 9, 'Winter': 12}
            start_date = datetime(year, seasons[period_name], 1)
            end_date = start_date + relativedelta(months=3) 
        else:  # Month
            try:
                month = datetime.strptime(period_name, '%B').month
                start_date = datetime(year, month, 1)
                end_date = start_date + relativedelta(months=1) 
            except ValueError:
                return f"Error: Invalid month name '{period_name}'"

        return {
            "start_date": start_date.strftime('%Y-%m-%dT%H:%M:%SZ'), 
            "end_date": end_date.strftime('%Y-%m-%dT%H:%M:%SZ')
        }
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"
     
def get_agent_handled_cases_by_period(start_date, end_date, sf_connector=None):
    """
    Retrieve the number of cases handled by each agent within a specified time period.

    This function queries the Salesforce CaseHistory__c object to count the number of cases
    assigned to each agent between the given start and end dates.

    Parameters:
    - start_date (str): The start date of the period in Salesforce datetime format (e.g., '2023-01-01T00:00:00Z').
    - end_date (str): The end date of the period in Salesforce datetime format (e.g., '2023-12-31T23:59:59Z').

    Returns:
    - dict: A dictionary where keys are agent IDs and values are the number of cases handled by each agent.
    - str: An error message if any error occurs during execution.

    Note:
    - This function assumes that case assignment is tracked in the CaseHistory__c object with 'Owner Assignment' as the Field__c value.
    - The function uses the Salesforce API to query data, so it requires proper authentication and permissions.
    """
    try:
        # Validate input parameters
        if not isinstance(start_date, str) or not isinstance(end_date, str):
            return "Error: start_date and end_date must be strings"

        # Attempt to parse dates to ensure they are in the correct format
        try:
            datetime.strptime(start_date, '%Y-%m-%dT%H:%M:%SZ')
            datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            return "Error: Invalid date format. Use 'YYYY-MM-DDTHH:MM:SSZ'"

        query = f"""
            SELECT NewValue__c, CreatedDate
            FROM CaseHistory__c
            WHERE CreatedDate >= {start_date} AND CreatedDate <= {end_date} AND Field__c = 'Owner Assignment'
        """
        
        result, status = sf_connector.run_query(query)
        if status == 0:
            return result
        if len(result) == 0:
            return {}
        records = result
        # Execute the query and handle potential Salesforce API errors
        # try:
        #     records = sf_connector.run_query(query)['records']
        # except Exception as e:
        #     return f"Error: Failed to query Salesforce API - {str(e)}"

        agent_handled_cases = defaultdict(int)
        for record in records:
            agent_id = record.get('NewValue__c')
            
            agent_handled_cases[agent_id] += 1
            

        return agent_handled_cases

    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"

def get_qualified_agent_ids_by_case_count(agent_handled_cases, n_cases, sf_connector=None):
    """
    Filters agent IDs based on the number of cases they have handled.

    This function takes a dictionary of agent IDs and their respective case counts
    and returns a list of agent IDs that have handled more than the specified number of cases.

    Parameters:
    - agent_handled_cases (dict): A dictionary where keys are agent IDs and values are the number of cases handled by each agent.
    - n_cases (int): The minimum number of cases an agent must have handled to be included.

    Returns:
    - list: A list of agent IDs that have handled more than n_cases cases.
    - str: An error message if any error occurs during execution.
    """
    try:
        # Check if agent_handled_cases is a dictionary
        if not isinstance(agent_handled_cases, dict):
            return "Error: agent_handled_cases must be a dictionary"

        # Check if n_cases is an integer
        if not isinstance(n_cases, int):
            return "Error: n_cases must be an integer"

        # Filter agent IDs based on case count
        qualified_agents = [agent_id for agent_id, count in agent_handled_cases.items() if count > n_cases]

        return qualified_agents

    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"

def get_cases(start_date=None, end_date=None, agent_ids=None, case_ids=None, order_item_ids=None, issue_ids=None, statuses=None, sf_connector=None):
    """
    Retrieve cases based on various filtering criteria.

    This function queries the Salesforce Case object to fetch cases that match the specified criteria.

    Parameters:
    - start_date (str): The start date of the period in Salesforce datetime format (e.g., '2023-01-01T00:00:00Z').
    - end_date (str): The end date of the period in Salesforce datetime format (e.g., '2023-12-31T23:59:59Z').
    - agent_ids (list): A list of agent IDs (User ID) to filter cases by.
    - case_ids (list): A list of case IDs to filter cases by.
    - order_item_ids (list): A list of order item IDs (OrderItem__c ID) to filter cases by.
    - issue_ids (list): A list of issue IDs (Issue__c ID) to filter cases by.
    - statuses (list): A list of case statuses to filter cases by.

    Returns:
    - list: A list of case records that match the specified criteria.
    - str: An error message if any error occurs during execution.
    """
    try:
        query = f"""
            SELECT OwnerId, CreatedDate, ClosedDate, AccountId
            FROM Case
        """
        
        condition = []
        if start_date:
            if not isinstance(start_date, str):
                return "Error: start_date must be a string in Salesforce datetime format"
            try:
                datetime.strptime(start_date, '%Y-%m-%dT%H:%M:%SZ')
                condition += [f"CreatedDate >= {start_date}"]
            except ValueError:
                return "Error: start_date must be in the format 'YYYY-MM-DDTHH:MM:SSZ'"
        
        if end_date:
            if not isinstance(end_date, str):
                return "Error: end_date must be a string in Salesforce datetime format"
            try:
                datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ')
                condition += [f"CreatedDate < {end_date}"]
            except ValueError:
                return "Error: end_date must be in the format 'YYYY-MM-DDTHH:MM:SSZ'"
            
        if agent_ids:
            if not isinstance(agent_ids, list):
                return "Error: agent_ids must be a list"
            if len(agent_ids) == 1:
                condition += [f"OwnerId = '{agent_ids[0]}'"]
            else:
                condition += [f"OwnerId IN {tuple(agent_ids)}"]
        if case_ids:
            if not isinstance(case_ids, list):
                return "Error: case_ids must be a list"
            if len(case_ids) == 1:
                condition += [f"Id = '{case_ids[0]}'"]
            else:
                condition += [f"Id IN {tuple(case_ids)}"]
                
        if order_item_ids:
            if not isinstance(order_item_ids, list):
                return "Error: order_item_ids must be a list"
            if len(order_item_ids) == 1:
                condition += [f"OrderItemId__c = '{order_item_ids[0]}'"]
            else:
                condition += [f"OrderItemId__c IN {tuple(order_item_ids)}"]
                
        if issue_ids:
            if not isinstance(issue_ids, list):
                return "Error: issue_ids must be a list"
            if len(issue_ids) == 1:
                condition += [f"IssueId__c = '{issue_ids[0]}'"]
            else:
                condition += [f"IssueId__c IN {tuple(issue_ids)}"]
                
        if statuses:
            if not isinstance(statuses, list):
                return "Error: statuses must be a list"
            if len(statuses) == 1:
                condition += [f"Status = '{statuses[0]}'"]
            else:
                condition += [f"Status IN {tuple(statuses)}"]
        
        if not condition:
            return "Error: At least one filter criteria must be provided"
        
        condition = " AND ".join(condition)
        
        query = f"{query} WHERE {condition}"
        
        result, _ = sf_connector.run_query(query)
        return result
        # try:
        #     return sf_connector.run_query(query)["records"]
        # except Exception as e:
        #     return f"Error: Failed to query Salesforce API - {str(e)}"
    
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"

def get_non_transferred_case_ids(start_date, end_date, sf_connector=None):
    """
    Retrieves the IDs of cases that were not transferred between agents within a specified date range.

    This function queries the CaseHistory__c object to find cases where the 'Owner Assignment' field
    was only changed once, indicating that these cases were not transferred to other agents after
    their initial assignment.

    Parameters:
        start_date (str): The start date of the period to check, in Salesforce datetime format (e.g., '2023-01-01T00:00:00Z').
        end_date (str): The end date of the period to check, in Salesforce datetime format (e.g., '2023-12-31T23:59:59Z').

    Returns:
        list: A list of CaseId__c values for cases that were not transferred during the specified period.
        str: An error message if an exception occurs.
    """
    try:
        if not isinstance(start_date, str) or not isinstance(end_date, str):
            return "Error: start_date and end_date must be strings"
        
        try:
            datetime.strptime(start_date, '%Y-%m-%dT%H:%M:%SZ')
            datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            return "Error: start_date and end_date must be in the format 'YYYY-MM-DDTHH:MM:SSZ'"

        query = f"""
            SELECT CaseId__c
            FROM CaseHistory__c
            WHERE Field__c = 'Owner Assignment'
            AND CreatedDate >= {start_date} AND CreatedDate <= {end_date}
            GROUP BY CaseId__c
            HAVING COUNT(Id) = 1
        """
        
        result, status = sf_connector.run_query(query)
        if status == 0:
            return result
        
        # if 'records' not in results:
        #     return "Error: Unexpected response format from Salesforce API"
        
        return [record['CaseId__c'] for record in result]
    
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"
    

    
def get_agent_transferred_cases_by_period(start_date, end_date, qualified_agent_ids=[], sf_connector=None):
    """
    Retrieves the number of cases transferred between agents within a specified date range.

    This function queries the CaseHistory__c object to count the number of cases where the 'Owner Assignment' field
    was changed, indicating a transfer to another agent.

    Parameters:
    - start_date (str): The start date of the period to check, in Salesforce datetime format (e.g., '2023-01-01T00:00:00Z').
    - end_date (str): The end date of the period to check, in Salesforce datetime format (e.g., '2023-12-31T23:59:59Z').
    - qualified_agent_ids (list): A list of agent IDs (User ID) to filter cases by.

    Returns:
    - dict: A dictionary where keys are agent IDs and values are the number of cases transferred to them.
    - str: An error message if an exception occurs.
    """
    try:
        if not isinstance(start_date, str) or not isinstance(end_date, str):
            return "Error: start_date and end_date must be strings"
        
        if not isinstance(qualified_agent_ids, list):
            return "Error: qualified_agent_ids must be a list"
        
        try:
            datetime.strptime(start_date, '%Y-%m-%dT%H:%M:%SZ')
            datetime.strptime(end_date, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            return "Error: start_date and end_date must be in the format 'YYYY-MM-DDTHH:MM:SSZ'"

        query = f"""
            SELECT OldValue__c, CreatedDate
            FROM CaseHistory__c
            WHERE Field__c = 'Owner Assignment'
            AND OldValue__c != NULL
            AND CreatedDate >= {start_date} AND CreatedDate <= {end_date}
        """
        
        result, status = sf_connector.run_query(query)
        if status == 0:
            return result
        
        # result = sf_connector.run_query(query)
        
        # if 'records' not in result:
        #     return "Error: Unexpected response format from Salesforce API"
        
        records = result
        
        agent_transfer_counts = defaultdict(int)
        for record in records:
            if 'OldValue__c' not in record:
                continue
            agent_id = record['OldValue__c']
            
            if qualified_agent_ids and agent_id not in qualified_agent_ids:
                continue
            agent_transfer_counts[agent_id] += 1
        
        return dict(agent_transfer_counts)
    
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"
    
        
        

def get_shipping_state(cases, sf_connector=None):
    """
    Adds shipping state information to the given cases.

    This function retrieves the shipping state for each case's associated account
    and adds it to the case data. 

    Parameters:
    - cases (list): A list of dictionaries, where each dictionary represents a case
                    and contains at least 'AccountId' key.

    Returns:
    - list: The input list of cases, with each case dictionary updated to include
            a 'ShippingState' key. 
    - str: An error message if an exception occurs.
    """
    try:
        if not isinstance(cases, list):
            return "Error: Input 'cases' must be a list"

        if not cases:
            return cases

        for case in cases:
            if not isinstance(case, dict):
                return "Error: Each case in 'cases' must be a dictionary"
            if 'AccountId' not in case:
                return "Error: Each case dictionary must contain an 'AccountId' key"

        account_ids = [case['AccountId'] for case in cases]
        query = f"""
            SELECT Id, ShippingState
            FROM Account
        """
        if len(account_ids) == 1:
            query += f" WHERE Id = '{account_ids[0]}'"
        else:
            query += f" WHERE Id IN {tuple(account_ids)}"
        
        result, status = sf_connector.run_query(query)
        if status == 0:
            return result
        # if 'records' not in result:
        #     return "Error: Unexpected response format from Salesforce API"

        account_states = {record['Id']: record['ShippingState'] for record in result}
        
        for case in cases:
            case['ShippingState'] = account_states.get(case['AccountId'], None)
        
        return cases
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"

def calculate_region_average_closure_times(cases, sf_connector=None):
    """
    Calculates the average closure times for cases grouped by region (shipping state).

    This function processes a list of cases, calculating the average time it takes
    to close cases for each region (represented by the shipping state). It uses the
    creation and closure dates of each case to compute the closure time.

    Parameters:
    - cases (list): A list of dictionaries, where each dictionary represents a case
                    and contains at least 'ShippingState', 'CreatedDate', and 'ClosedDate' keys.

    Returns:
    - dict: A dictionary where keys are regions (shipping states) and values are
            the average closure times (in seconds) for that region.
    - str: An error message if an exception occurs.

    Note:
    - Cases without a shipping state are ignored.
    - The function assumes 'CreatedDate' and 'ClosedDate' are in ISO format with timezone information.
    """
    try:
        if not isinstance(cases, list):
            return "Error: Input 'cases' must be a list"

        if not cases:
            return "Error: Input 'cases' is empty"

        region_closure_times = defaultdict(list)
        for case in cases:
            if not isinstance(case, dict):
                return "Error: Each case in 'cases' must be a dictionary"
            
            if 'ShippingState' not in case or 'CreatedDate' not in case or 'ClosedDate' not in case:
                return "Error: Each case dictionary must contain 'ShippingState', 'CreatedDate', and 'ClosedDate' keys"
            
            state = case['ShippingState']
            if state:
                try:
                    created_date = datetime.strptime(case['CreatedDate'], '%Y-%m-%dT%H:%M:%S.%f%z')
                    closed_date = datetime.strptime(case['ClosedDate'], '%Y-%m-%dT%H:%M:%S.%f%z')
                except ValueError:
                    return "Error: Invalid date format. Dates should be in the format 'YYYY-MM-DDTHH:MM:SSZ'"
                
                closure_time = (closed_date - created_date).total_seconds() 
                region_closure_times[state].append(closure_time)


        return {region: sum(times) / len(times) for region, times in region_closure_times.items()}
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"

    
def get_order_item_ids_by_product(product_id, sf_connector=None):
    """
    Retrieves the order item IDs associated with a given product.

    Parameters:
    - product_id (str): The ID of the product.

    Returns:
    - list: A list of order item IDs.
    - str: An error message if an exception occurs.
    """
    try:
        if not isinstance(product_id, str):
            return "Error: product_id must be a string"

        if not product_id:
            return "Error: product_id cannot be empty"

        query = f"""
            SELECT Id
            FROM OrderItem
            WHERE Product2Id = '{product_id}'
        """
        
        result, status = sf_connector.run_query(query)
        if status == 0:
            return result
        
        # if 'records' not in result:
        #     return "Error: Unexpected response format from Salesforce"
        
        return [record["Id"] for record in result]
    
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"

def get_issue_counts(start_date, end_date, order_item_ids, sf_connector=None):
    """
    Retrieves the issue counts for a product within a given time period.

    Parameters:
    - start_date (str): The start date of the time period (format: 'YYYY-MM-DDTHH:MM:SSZ').
    - end_date (str): The end date of the time period (format: 'YYYY-MM-DDTHH:MM:SSZ').
    - order_item_ids (list): A list of order item IDs (OrderItem__c ID) to filter issues by.

    Returns:
    - dict: A dictionary with issue IDs as keys and their counts as values.
    - str: An error message if an exception occurs.
    """
    try:
        # Input validation
        if not isinstance(start_date, str) or not isinstance(end_date, str):
            return "Error: start_date and end_date must be strings"
        if not isinstance(order_item_ids, list) or not order_item_ids:
            return "Error: order_item_ids must be a non-empty list"

        query = f"""
            SELECT IssueId__c, COUNT(Id) IssueCount
            FROM Case
            WHERE OrderItemId__c IN ('{"','".join(map(str, order_item_ids))}')
            AND CreatedDate >= {start_date}
            AND CreatedDate <= {end_date}
            GROUP BY IssueId__c
            ORDER BY COUNT(Id) DESC
        """
        
        # result = sf_connector.run_query(query)
        result, status = sf_connector.run_query(query)
        if status == 0:
            return result
        # if 'records' not in result:
        #     return "Error: Unexpected response format from Salesforce"
        
        return {record["IssueId__c"]: record["IssueCount"] for record in result}
    
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"


def find_id_with_max_value(values_by_id, sf_connector=None):
    """
    Identifies the ID with the maximum value from a dictionary.

    Parameters:
    - values_by_id (dict): A dictionary with IDs as keys and their corresponding values.

    Returns:
    - str: The ID with the maximum value, or None if the dictionary is empty.
    - str: An error message if an exception occurs.
    """
    try:
        if not isinstance(values_by_id, dict):
            return "Error: Input must be a dictionary"
        
        if not values_by_id:
            return None
        
        if not all(isinstance(value, (int, float)) for value in values_by_id.values()):
            return "Error: All values in the dictionary must be numeric"
        
        max_value = max(values_by_id.values())
        return [key for key, value in values_by_id.items() if value == max_value]
    
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"
    
def find_id_with_min_value(values_by_id, sf_connector=None):
    """
    Identifies the ID with the minimum value from a dictionary.

    Parameters:
    - values_by_id (dict): A dictionary with IDs as keys and their corresponding values.

    Returns:
    - str: The ID with the minimum value, or None if the dictionary is empty.
    - str: An error message if an exception occurs.
    """
    try:
        if not isinstance(values_by_id, dict):
            return "Error: Input must be a dictionary"
        
        if not values_by_id:
            return None
        
        if not all(isinstance(value, (int, float)) for value in values_by_id.values()):
            return "Error: All values in the dictionary must be numeric"
        
        min_value = min(values_by_id.values())
        return [key for key, value in values_by_id.items() if value == min_value]
    
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"


def get_account_id_by_contact_id(contact_id: str, sf_connector=None):
    """
    Retrieves the Account ID associated with a given Contact ID.

    Parameters:
    - contact_id (str): The ID of the contact.

    Returns:
    - str: The ID of the associated account, or None if not found.
    - str: An error message if an exception occurs.
    """
    try:
        if not isinstance(contact_id, str):
            return "Error: contact_id must be a string"

        if not contact_id:
            return "Error: contact_id cannot be empty"

        query = f"""
            SELECT AccountId
            FROM Contact
            WHERE Id = '{contact_id}'
            LIMIT 1
        """
        result, status = sf_connector.run_query(query)
        if status == 0:
            return result
        if len(result) > 0:
            return result[0]['AccountId']
        return result
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"

def get_purchase_history(account_id, purchase_date, related_product_ids, sf_connector=None):
    
    """
    Retrieves the purchase history for a specific account, date, and set of products.

    This function queries the Salesforce database to find OrderItems that match
    the given criteria: the specified account, purchase date, and product IDs.

    Parameters:
    - account_id (str): The ID of the account to search for.
    - purchase_date (str): The date of purchase in 'YYYY-MM-DDTHH:MM:SSZ' format.
    - related_product_ids (list): A list of product IDs to search for.

    Returns:
    - list: A list of dictionaries, where each dictionary represents an OrderItem
            record that matches the criteria. Each dictionary contains the 'Product2Id'
            field. Returns an empty list if no matching records are found.
    - str: An error message if an exception occurs.

    Note:
    - This function only returns OrderItems from Orders with a 'Status' of 'Activated'.
    - The purchase date is compared only to the date part of the Order's EffectiveDate.
    
    """
    try:
        # Input validation
        if not isinstance(account_id, str):
            return "Error: account_id must be a string"
        if not isinstance(purchase_date, str):
            return "Error: purchase_date must be a string"
        if not isinstance(related_product_ids, list):
            return "Error: related_product_ids must be a list"
        if not all(isinstance(id, str) for id in related_product_ids):
            return "Error: All product IDs in related_product_ids must be strings"
        
        # Validate date format
        try:
            datetime.strptime(purchase_date, '%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            return "Error: purchase_date must be in 'YYYY-MM-DDTHH:MM:SSZ' format"

        query = f"""
            SELECT Product2Id
            FROM OrderItem
            WHERE OrderItem.Order.AccountId = '{account_id}'
            AND OrderItem.Order.EffectiveDate = {purchase_date.split("T")[0]}
            AND Product2Id IN ('{"','".join(related_product_ids)}')
            AND OrderItem.Order.Status = 'Activated'
        """
        
        result, _ = sf_connector.run_query(query)
        return result
        # return result["records"]
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"


    
def get_month_to_case_count(cases, sf_connector=None):    
    """
    Counts the number of cases for each month from a list of cases.

    Parameters:
    - cases (list): A list of dictionaries, where each dictionary represents a case
                    and contains at least a 'CreatedDate' key with a value in the format
                    'YYYY-MM-DDTHH:MM:SSZ'.
    Returns:
    - dict: A dictionary where keys are month names (e.g., 'January', 'February', etc.)
            and values are the count of cases created in that month.
    - str: An error message if an exception occurs.
    """
    try:
        # Input validation
        if not isinstance(cases, list):
            return "Error: Input must be a list of dictionaries"

        # Group cases by month
        case_counts = defaultdict(int)
        for case in cases:
            if not isinstance(case, dict):
                return "Error: Each case must be a dictionary"
            if 'CreatedDate' not in case:
                return "Error: Each case dictionary must contain a 'CreatedDate' key"
            
            try:
                case_date = datetime.strptime(case['CreatedDate'], '%Y-%m-%dT%H:%M:%S.%f%z')
            except ValueError:
                return "Error: Invalid date format. Expected format: 'YYYY-MM-DDTHH:MM:SSZ'"
            
            # convert this to January, February, ..., December
            month_key = case_date.strftime('%B')
            case_counts[month_key] += 1
        
        return dict(case_counts)  # Convert defaultdict to regular dict before returning
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"
    

# todo
def search_knowledge_articles(search_term, sf_connector=None):    
    """
    Searches for knowledge articles based on a given search term.

    This function performs a Salesforce Object Search Language (SOSL) query to find
    knowledge articles that match the provided search term. It searches across all
    fields of the Knowledge__kav object.

    Parameters:
    - search_term (str): The term to search for in the knowledge articles.

    Returns:
    - list: A list of dictionaries, where each dictionary represents a matching
            knowledge article with the following keys:
            - 'Id': The unique identifier of the article.
            - 'Title': The title of the article.
            - 'Content': The content of the article (FAQ_Answer__c field).
    - str: An error message if an exception occurs.

    Note:
    - If no matching articles are found, an empty list is returned.
    """
    try:
        if not isinstance(search_term, str):
            return "Error: search_term must be a string"

        if not search_term.strip():
            return "Error: search_term cannot be empty"

        sosl_query = f"""\
            FIND {{{search_term}}} IN ALL FIELDS RETURNING Knowledge__kav(Id, Title, FAQ_Answer__c WHERE PublishStatus='Online' AND Language='en_US')
        """.strip()
        
        result, status = sf_connector.run_query(sosl_query)
        if status == 0:
            return result
        
        articles = []
        for record in result:
            articles.append({
                'Id': record.get('Id', ''),
                'Title': record.get('Title', ''),
                'Content': record.get('FAQ_Answer__c', '')
            })
        
        return articles
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"

def search_products(search_term, sf_connector=None):
    """
    Searches for products based on a given search term.

    This function performs a Salesforce Object Search Language (SOSL) query to find
    products that match the provided search term. It searches across all fields of
    the Product2 object.

    Parameters:
    - search_term (str): The term to search for in the products.

    Returns:
    - list: A list of product IDs that match the search term.
    - str: An error message if an exception occurs.

    Note:
    - If no matching products are found, an empty list is returned.
    """
    try:
        if not isinstance(search_term, str):
            return "Error: search_term must be a string"

        if not search_term.strip():
            return "Error: search_term cannot be empty"

        sosl_query = f"""FIND {{{search_term}}} IN ALL FIELDS RETURNING Product2(Id, Name, Description)
        """.strip()
        
        result, status = sf_connector.run_query(sosl_query)
        if status == 0:
            return result
        products = []
        for record in result:
            products.append(record['Id'])
        return products
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"

def get_issues(sf_connector=None):
    """
    Retrieves a list of issue records from Salesforce.

    This function queries the Issue__c object in Salesforce to retrieve all issue records.

    Returns:
    - list: A list of dictionaries, where each dictionary represents an issue record.
    - str: An error message if an exception occurs.
    """
    try:
        query = """
            SELECT Id, Name
            FROM Issue__c
        """
        result, _ = sf_connector.run_query(query)
        return result
        # if 'records' not in result:
        #     return "Error: Unexpected response format from Salesforce"
        # return result['records']
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"
  
def respond(content, sf_connector=None):
    '''
    Returns the response content.
    '''
    return content


def get_email_messages_by_case_id(case_id, sf_connector=None):
    """
    Retrieves email messages associated with a specific case ID.

    This function queries the EmailMessage object in Salesforce to retrieve all email messages
    associated with the given case ID.

    Parameters:
    - case_id (str): The ID of the case to retrieve email messages for.

    
    """
    try:        
        if not isinstance(case_id, str):
            return "Error: case_id must be a string"

        query = f"""
            SELECT Subject, TextBody, FromAddress, ToAddress, MessageDate
            FROM EmailMessage
            WHERE ParentId = '{case_id}'
        """
        result, status = sf_connector.run_query(query)
        return result
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"
    

def get_livechat_transcript_by_case_id(case_id, sf_connector=None):
    """
    Retrieves live chat transcripts associated with a specific case ID.

    This function queries the LiveChatTranscript object in Salesforce to retrieve all live chat transcripts
    associated with the given case ID.

    Parameters:
    - case_id (str): The ID of the case to retrieve live chat transcripts for.

    
    """
    try:        
        if not isinstance(case_id, str):
            return "Error: case_id must be a string"

        query = f"""
            SELECT Body, EndTime
            FROM LiveChatTranscript
            WHERE CaseId = '{case_id}'
        """
        result, _ = sf_connector.run_query(query)
        return result
    except Exception as e:
        return f"Error: An unexpected error occurred - {str(e)}"
    
def issue_soql_query(query, sf_connector=None):
    result, _ = sf_connector.run_query(query)
    return result


def issue_sosl_query(query, sf_connector=None):
    result, _ = sf_connector.run_query(query)
    return result


# Produce docstrings for functions
get_agents_with_max_cases.__info__ = {
    "type": "function",
    "function": {
        "name": "get_agents_with_max_cases",
        "description": "Returns a list of agent IDs with the maximum number of cases from the given subset of cases.",
        "parameters": {
            "type": "object",
            "properties": {
                "subset_cases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "OwnerId": {
                                "type": "string",
                                "description": "The ID of the agent who owns the case"
                            }
                        },
                        "required": ["OwnerId"]
                    },
                    "description": "A list of case records, where each record is expected to have an 'OwnerId' field representing the agent ID., where each item should be object",
                },
            },
            "required": ["subset_cases"],
        },
        "returns": {
            "type": "array",
            "description": "A list of agent IDs (strings) who have handled the maximum number of cases. Returns an empty list if no cases are provided.",
        },
    },
}



get_agents_with_min_cases.__info__ = {
    "type": "function",
    "function": {
        "name": "get_agents_with_min_cases",
        "description": "Returns a list of agent IDs with the minimum number of cases from the given subset of cases.",
        "parameters": {
            "type": "object",
            "properties": {
                "subset_cases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "OwnerId": {
                                "type": "string",
                                "description": "The ID of the agent who owns the case"
                            }
                        },
                        "required": ["OwnerId"]
                    },
                    "description": "A list of case records, where each record is expected to have an 'OwnerId' field representing the agent ID., where each item should be object",
                },
            },
            "required": ["subset_cases"],
        },
        "returns": {
            "type": "array",
            "description": "A list of agent IDs (strings) who have handled the minimum number of cases. Returns an empty list if no cases are provided.",
        },
    },
}

calculate_average_handle_time.__info__ = {
    "type": "function",
    "function": {
        "name": "calculate_average_handle_time",
        "description": "Calculate the average handle time for each agent based on a list of cases.",
        "parameters": {
            "type": "object",
            "properties": {
                "cases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "CreatedDate": {
                                "type": "string",
                                "description": "The date and time when the case was created"
                            },
                            "ClosedDate": {
                                "type": "string",
                                "description": "The date and time when the case was closed"
                            },
                            "OwnerId": {
                                "type": "string",
                                "description": "The ID of the agent who owns the case"
                            }
                        },
                        "required": ["CreatedDate", "ClosedDate", "OwnerId"]
                    },
                    "description": "A list of case dictionaries. Each case should have 'CreatedDate', 'ClosedDate', and 'OwnerId' keys., where each item should be object",
                },
            },
            "required": ["cases"],
        },
        "returns": {
            "type": "object",
            "description": "A dictionary where keys are agent IDs (OwnerId) and values are their average handle times in minutes.",
        },
    },
}

get_start_date.__info__ = {
    "type": "function",
    "function": {
        "name": "get_start_date",
        "description": "Calculate the start date based on the end date, period, and interval count.",
        "parameters": {
            "type": "object",
            "properties": {
                "end_date": {
                    "type": "string",
                    "description": "The end date in ISO format 'YYYY-MM-DDTHH:MM:SSZ'.",
                },
                "period": {
                    "type": "string",
                    "description": "The time period unit ('day', 'week', 'month', or 'quarter').",
                },
                "interval_count": {
                    "type": "integer",
                    "description": "The number of periods to subtract from the end date.",
                },
            },
            "required": ["end_date", "period", "interval_count"],
        },
        "returns": {
            "type": "string",
            "description": "The calculated start date in ISO format 'YYYY-MM-DDTHH:MM:SSZ'.",
        },
    },
}

get_period.__info__ = {
    "type": "function",
    "function": {
        "name": "get_period",
        "description": "Calculate the start and end date based on the period name and year.",
        "parameters": {
            "type": "object",
            "properties": {
                "period_name": {
                    "type": "string",
                    "description": "The name of the period ('January', 'February', ..., 'December', 'Q1', 'Q2', 'Q3', 'Q4', 'Spring', 'Summer', 'Fall', 'Winter').",
                },
                "year": {
                    "type": "integer",
                    "description": "The year in which the period falls.",
                },
            },
            "required": ["period_name", "year"],
        },
        "returns": {
            "type": "object",
            "description": "A dictionary with 'start_date' and 'end_date' keys, both in ISO format 'YYYY-MM-DDTHH:MM:SSZ'.",
        },
    },
}

get_agent_handled_cases_by_period.__info__ = {
    "type": "function",
    "function": {
        "name": "get_agent_handled_cases_by_period",
        "description": "Retrieve the number of cases handled by each agent within a specified time period.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "The start date of the period in Salesforce datetime format (e.g., '2023-01-01T00:00:00Z').",
                },
                "end_date": {
                    "type": "string",
                    "description": "The end date of the period in Salesforce datetime format (e.g., '2023-12-31T23:59:59Z').",
                },
            },
            "required": ["start_date", "end_date"],
        },
        "returns": {
            "type": "object",
            "description": "A dictionary where keys are agent IDs and values are the number of cases handled by each agent.",
        },
    },
}

get_qualified_agent_ids_by_case_count.__info__ = {
    "type": "function",
    "function": {
        "name": "get_qualified_agent_ids_by_case_count",
        "description": "Filters agent IDs based on the number of cases they have handled.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_handled_cases": {
                    "type": "object",
                    "description": "A dictionary where keys are agent IDs and values are the number of cases handled by each agent.",
                },
                "n_cases": {
                    "type": "integer",
                    "description": "The minimum number of cases an agent must have handled to be included.",
                },
            },
            "required": ["agent_handled_cases", "n_cases"],
        },
        "returns": {
            "type": "array",
            "description": "A list of agent IDs that have handled more than n_cases cases.",
        },
    },
}

get_cases.__info__ = {
    "type": "function",
    "function": {
        "name": "get_cases",
        "description": "Retrieve cases based on various filtering criteria.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "The start date of the period in Salesforce datetime format (e.g., '2023-01-01T00:00:00Z').",
                },
                "end_date": {
                    "type": "string",
                    "description": "The end date of the period in Salesforce datetime format (e.g., '2023-12-31T23:59:59Z').",
                },
                "agent_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "A list of agent IDs (User ID) to filter cases by., where each item should be string",
                },
                "case_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "A list of case IDs to filter cases by., where each item should be string",
                },
                "order_item_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "A list of order item IDs (OrderItem__c ID) to filter cases by., where each item should be string",
                },
                "issue_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "A list of issue IDs (Issue__c ID) to filter cases by., where each item should be string",
                },
                "statuses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "A list of case statuses to filter cases by., where each item should be string",
                },
            },
            "required": [],
        },
        "returns": {
            "type": "array",
            "description": "A list of case records that match the specified criteria.",
        },
    },
}


get_non_transferred_case_ids.__info__ = {
    "type": "function",
    "function": {
        "name": "get_non_transferred_case_ids",
        "description": "Retrieves the IDs of cases that were not transferred between agents within a specified date range.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "The start date of the period in Salesforce datetime format (e.g., '2023-01-01T00:00:00Z').",
                },
                "end_date": {
                    "type": "string",
                    "description": "The end date of the period in Salesforce datetime format (e.g., '2023-12-31T23:59:59Z').",
                },
            },
            "required": ["start_date", "end_date"],
        },
        "returns": {
            "type": "array",
            "description": "A list of CaseId__c values for cases that were not transferred during the specified period.",
        },
    },
}

get_agent_transferred_cases_by_period.__info__ = {
    "type": "function",
    "function": {
        "name": "get_agent_transferred_cases_by_period",
        "description": "Retrieves the number of cases transferred between agents within a specified date range.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "The start date of the period to check, in Salesforce datetime format (e.g., '2023-01-01T00:00:00Z').",
                },
                "end_date": {
                    "type": "string",
                    "description": "The end date of the period to check, in Salesforce datetime format (e.g., '2023-12-31T23:59:59Z').",
                },
                "qualified_agent_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "A list of agent IDs (User ID) to filter cases by., where each item should be string",
                },
            },
            "required": ["start_date", "end_date"],
        },
        "returns": {
            "type": "object",
            "description": "A dictionary where keys are agent IDs and values are the number of cases transferred to them.",
        },
    },
}



get_shipping_state.__info__ = {
    "type": "function",
    "function": {
        "name": "get_shipping_state",
        "description": "Adds shipping state information to the given cases.",
        "parameters": {
            "type": "object",
            "properties": {
                "cases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "AccountId": {
                                "type": "string",
                                "description": "The ID of the account associated with the case"
                            }
                        },
                        "required": ["AccountId"]
                    },
                    "description": "A list of dictionaries, where each dictionary represents a case and contains at least 'AccountId' key., where each item should be object",
                },
            },
            "required": ["cases"],
        },
        "returns": {
            "type": "array",
            "items": {"type": "object"},
            "description": "The input list of cases, with each case dictionary updated to include a 'ShippingState' key.",
        },
    },
}


calculate_region_average_closure_times.__info__ = {
    "type": "function",
    "function": {
        "name": "calculate_region_average_closure_times",
        "description": "Calculates the average closure times for cases grouped by region (shipping state).",
        "parameters": {
            "type": "object",
            "properties": {
                "cases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ShippingState": {
                                "type": "string",
                                "description": "The shipping state of the case"
                            },
                            "CreatedDate": {
                                "type": "string",
                                "description": "The date and time when the case was created"
                            },
                            "ClosedDate": {
                                "type": "string",
                                "description": "The date and time when the case was closed"
                            }
                        },
                        "required": ["ShippingState", "CreatedDate", "ClosedDate"]
                    },
                    "description": "A list of dictionaries, where each dictionary represents a case and contains at least 'ShippingState', 'CreatedDate', and 'ClosedDate' keys., where each item should be object",
                },
            },
            "required": ["cases"],
        },
        "returns": {
            "type": "object",
            "description": "A dictionary where keys are regions (shipping states) and values are the average closure times (in seconds) for that region.",
        },
    },
}


get_order_item_ids_by_product.__info__ = {
    "type": "function",
    "function": {
        "name": "get_order_item_ids_by_product",
        "description": "Retrieves the order item IDs associated with a given product.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_id": {
                    "type": "string",
                    "description": "The ID of the product.",
                },
            },
            "required": ["product_id"],
        },
        "returns": {
            "type": "array",
            "items": {"type": "string"},
            "description": "A list of order item IDs.",
        },
    },
}


get_issue_counts.__info__ = {
    "type": "function",
    "function": {
        "name": "get_issue_counts",
        "description": "Retrieves the issue counts for a product within a given time period.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "The start date of the time period (format: 'YYYY-MM-DDTHH:MM:SSZ').",
                },
                "end_date": {
                    "type": "string",
                    "description": "The end date of the time period (format: 'YYYY-MM-DDTHH:MM:SSZ').",
                },
                "order_item_ids": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "A list of order item IDs to filter issues by., where each item should be string",
                },
            },
            "required": ["start_date", "end_date", "order_item_ids"],
        },
        "returns": {
            "type": "object",
            "description": "A dictionary with issue IDs as keys and their counts as values.",
        },
    },
}




find_id_with_max_value.__info__ = {
    "type": "function",
    "function": {
        "name": "find_id_with_max_value",
        "description": "Identifies the ID with the maximum value from a dictionary.",
        "parameters": {
            "type": "object",
            "properties": {
                "values_by_id": {
                    "type": "object",
                    "description": "A dictionary with IDs as keys and their corresponding values.",
                },
            },
            "required": ["values_by_id"],
        },
        "returns": {
            "type": "string",
            "description": "The ID with the maximum value, or None if the dictionary is empty.",
        },
    },
}

find_id_with_min_value.__info__ = {
    "type": "function",
    "function": {
        "name": "find_id_with_min_value",
        "description": "Identifies the ID with the minimum value from a dictionary.",
        "parameters": {
            "type": "object",
            "properties": {
                "values_by_id": {
                    "type": "object",
                    "description": "A dictionary with IDs as keys and their corresponding values.",
                },
            },
            "required": ["values_by_id"],
        },
        "returns": {
            "type": "string",
            "description": "The ID with the minimum value, or None if the dictionary is empty.",
        },
    },
}


get_account_id_by_contact_id.__info__ = {
    "type": "function",
    "function": {
        "name": "get_account_id_by_contact_id",
        "description": "Retrieves the Account ID associated with a given Contact ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "The ID of the contact.",
                },
            },
            "required": ["contact_id"],
        },
        "returns": {
            "type": "string",
            "description": "The ID of the associated account, or None if not found.",
        },
    },
}


get_purchase_history.__info__ = {
    "type": "function",
    "function": {
        "name": "get_purchase_history",
        "description": "Retrieves the purchase history for a specific account, date, and set of products.",
        "parameters": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "The ID of the account to search for.",
                },
                "purchase_date": {
                    "type": "string",
                    "description": "The date of purchase in 'YYYY-MM-DD' format.",
                },
                "related_product_ids": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "A list of product IDs to search for., where each item should be string",
                },
            },
            "required": ["account_id", "purchase_date", "related_product_ids"],
        },
        "returns": {
            "type": "array",
            "items": {
                "type": "object"
            },
            "description": "A list of dictionaries, where each dictionary represents an OrderItem record that matches the criteria. Each dictionary contains the 'Product2Id' field. Returns an empty list if no matching records are found.",
        },
    },
}


get_month_to_case_count.__info__ = {
    "type": "function",
    "function": {
        "name": "get_month_to_case_count",
        "description": "Counts the number of cases for each month from a list of cases.",
        "parameters": {
            "type": "object",
            "properties": {
                "cases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "CreatedDate": {
                                "type": "string",
                                "description": "The date and time when the case was created, in the format 'YYYY-MM-DDTHH:MM:SSZ'."
                            }
                        },
                        "required": ["CreatedDate"]
                    },
                    "description": "A list of dictionaries, where each dictionary represents a case and contains at least a 'CreatedDate' key with a value in the format 'YYYY-MM-DDTHH:MM:SSZ'., where each item should be object",
                },
            },
            "required": ["cases"],
        },
        "returns": {
            "type": "object",
            "description": "A dictionary where keys are month names (e.g., 'January', 'February', etc.) and values are the count of cases created in that month.",
        },
    },
}


search_knowledge_articles.__info__ = {
    "type": "function",
    "function": {
        "name": "search_knowledge_articles",
        "description": "Searches for knowledge articles based on given keywords.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "A list of keywords to search for in knowledge articles.",
                }
            },
            "required": ["keywords"],
        },
        "returns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "Id": {"type": "string"},
                    "Title": {"type": "string"},
                    "UrlName": {"type": "string"}
                }
            },
            "description": "A list of dictionaries, where each dictionary represents a knowledge article that matches the search criteria. Returns an empty list if no matching articles are found.",
        },
    },
}


search_products.__info__ = {
    "type": "function",
    "function": {
        "name": "search_products",
        "description": "Searches for products based on a given search term.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "The term to search for in the products.",
                },
            },
            "required": ["search_term"],
        },
        "returns": {
            "type": "array",
            "items": {
                "type": "string"
            },
            "description": "A list of product IDs that match the search term. Returns an empty list if no matching products are found.",
        },
    },
}

get_issues.__info__ = {
    "type": "function",
    "function": {
        "name": "get_issues",
        "description": "Retrieves a list of issue records from Salesforce.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "returns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "Id": {"type": "string"},
                    "Name": {"type": "string"}
                }
            },
            "description": "A list of dictionaries, where each dictionary represents an issue record containing 'Id' and 'Name' fields."
        }
    }
}

respond.__info__ = {
    "type": "function",
    "function": {
        "name": "respond",
        "description": "Returns the input content without modification.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The content to be returned.",
                },
            },
            "required": ["content"],
        },
        "returns": {
            "type": "string",
            "description": "The input content, returned without any changes.",
        },
    },
}

get_email_messages_by_case_id.__info__ = {
    "type": "function",
    "function": {
        "name": "get_email_messages_by_case_id",
        "description": "Retrieves email messages associated with a specific case ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "case_id": {
                    "type": "string",
                    "description": "The ID of the case to retrieve email messages for.",
                },
            },
            "required": ["case_id"],
        },
    },
}

get_livechat_transcript_by_case_id.__info__ = {
    "type": "function",
    "function": {
        "name": "get_livechat_transcript_by_case_id",
        "description": "Retrieves live chat transcripts associated with a specific case ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "case_id": {
                    "type": "string",
                    "description": "The ID of the case to retrieve live chat transcripts for.",
                },
            },
            "required": ["case_id"],
        },
    },
}

issue_soql_query.__info__ = {
    "type": "function",
    "function": {
        "name": "issue_soql_query",
        "description": "Executes a SOQL (Salesforce Object Query Language) query to retrieve data from Salesforce.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The SOQL query string to execute.",
                },
            },
            "required": ["query"],
        },
    },
}

issue_sosl_query.__info__ = {
    "type": "function",
    "function": {
        "name": "issue_sosl_query",
        "description": "Executes a SOSL (Salesforce Object Search Language) query to search for records across multiple objects in Salesforce.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The SOSL query string to execute.",
                },
            },
            "required": ["query"],
        },
    },
}