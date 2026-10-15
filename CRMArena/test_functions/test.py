from functions import get_start_date, get_period, get_cases, get_shipping_state, calculate_region_average_closure_times, find_id_with_min_value, get_order_item_ids_by_product, get_issue_counts, find_id_with_max_value, get_month_to_case_count, get_agents_with_max_cases, get_agents_with_min_cases, get_account_id_by_contact_id, get_purchase_history, search_products, get_agent_handled_cases_by_period, get_qualified_agent_ids_by_case_count, get_non_transferred_case_ids, calculate_average_handle_time, get_agent_trasferred_cases_by_period

def get_best_region(end_date=None, period=None, interval_count=None, period_name=None, year=None):
    """
    TODO: delete
    Identifies the regions where cases are closed the fastest within the given time period.
    
    Parameters:
    - start_date (str): The start date for filtering cases (format: 'YYYY-MM-DDTHH:MM:SSZ').
    - end_date (str): The end date for filtering cases (format: 'YYYY-MM-DDTHH:MM:SSZ').
    
    Returns:
    - list: A list of regions (states) with the fastest case closure times.
    """
    if end_date is not None:
        start_date = get_start_date(end_date, period, interval_count)
    else:
        start_end_date = get_period(period_name, year)
        start_date = start_end_date['start_date']
        end_date = start_end_date['end_date']
        
    cases = get_cases(start_date=start_date, end_date=end_date, statuses=["Closed"])
    cases = get_shipping_state(cases)
    region_closure_times =  calculate_region_average_closure_times(cases)
    
    if not region_closure_times:
        return None
    
    return find_id_with_min_value(region_closure_times)


def get_top_issue_by_product(product_id, end_date=None, period=None, interval_count=None, period_name=None, year=None):
    """
    TODO: delete
    Identifies the most reported issue for a particular product within a given time period.

    Parameters:
    - start_date (str): The start date of the time period (format: 'YYYY-MM-DD').
    - end_date (str): The end date of the time period (format: 'YYYY-MM-DD').
    - product_id (str): The ID of the product to analyze.

    Returns:
    - str: The ID of the most reported issue, or None if no issues found.
    """
    if end_date is not None:
        start_date = get_start_date(end_date, period, interval_count)
    else:
        start_end_date = get_period(period_name, year)
        start_date = start_end_date['start_date']
        end_date = start_end_date['end_date']
    
    relevant_order_item_ids = get_order_item_ids_by_product(product_id)
    if not relevant_order_item_ids:
        return None
    
    issue_counts = get_issue_counts(start_date, end_date, relevant_order_item_ids)
    
    return find_id_with_max_value(issue_counts)


def get_disambiguiated_named_entity(ambiguous_product_name: str, contact_id: str, today_date=None, period=None, interval_count=None):
    """
    TODO: delete
    Identifies Id of the product based on an ambiguous product name bought by customer_id on purchase_date.

    Parameters:
    - ambiguous_product_name (str): A string of the ambiguous product name.
    - contact_id (str): The ID of the contact.
    - purchase_date (str): The date of purchase.
    
    Returns:
    - str: The ID of the product.
    """
    
    # compute purchase date based on today_date and period and interval
    purchase_date = get_start_date(today_date, period, interval_count)
    
    related_product_ids = search_products(ambiguous_product_name)
    
    if not related_product_ids:
        return None
    
    account_id = get_account_id_by_contact_id(contact_id)
    
    if not account_id:
        return None

    result = get_purchase_history(account_id, purchase_date, related_product_ids)
    
    if len(result) == 0:
        return None
    else:
        return result[0]['Product2Id']


def get_most_issue_month(product_id, end_date=None, period=None, interval_count=None, period_name=None, year=None):
    """
    TODO: delete
    Identifies the month with the highest number of cases for a given product within a specified time period.

    Parameters:
    - start_date (str): The start date of the time period (format: 'YYYY-MM-DD').
    - end_date (str): The end date of the time period (format: 'YYYY-MM-DD').
    - product_id (str): The ID of the product.

    Returns:
    - str: The month with the highest number of cases (format: 'YYYY-MM').
    """
    if end_date is not None:
        start_date = get_start_date(end_date, period, interval_count)
    else:
        start_end_date = get_period(period_name, year)
        start_date = start_end_date['start_date']
        end_date = start_end_date['end_date']
    
    relevant_order_item_ids = get_order_item_ids_by_product(product_id)
    
    cases = get_cases(start_date, end_date, order_item_ids=relevant_order_item_ids)
    
    if len(cases) == 0:
        return None
    month_to_case_count = get_month_to_case_count(cases)
    
    return find_id_with_max_value(month_to_case_count)


def get_best_assigned_agent(issue_id, product_id):
    """
    TODO: delete
    This function determines the best agent to be assigned to a case based on the given issue and product.
    
    The selection criteria are as follows:
    1. The agent who closed the most cases with the specified issue.
    2. If there is a tie, the agent who solved the most cases associated with the specified product.
    3. If there is still a tie, the agent who has the least number of open cases.
    
    Parameters:
    - issue_id (str): The ID of the issue.
    - product_id (str): The ID of the product.
    - start_date (str, optional): The start date for filtering cases (format: '2024-09-20T05:04:57').
    - end_date (str, optional): The end date for filtering cases (format: '2024-09-20T05:04:57.').
    
    Returns:
    - str: The ID of the best agent.
    """
    
    # Get cases with the same issue
    
    issue_cases = get_cases(issue_ids=[issue_id], statuses=["Closed"])
    
    issue_agent_ids = get_agents_with_max_cases(issue_cases)
    
    if len(issue_agent_ids) == 0:
        return None
    elif len(issue_agent_ids) == 1:
        return issue_agent_ids[0]
    
    # There is a tie. Check product cases
    
    relevant_order_item_ids = get_order_item_ids_by_product(product_id)
    
    product_cases = get_cases(order_item_ids=relevant_order_item_ids, agent_ids=issue_agent_ids, statuses=["Closed"])
    
    if len(product_cases) == 0:
        return None
    
    product_agent_ids = get_agents_with_max_cases(product_cases)
    
    if len(product_agent_ids) == 0:
        return None
    elif len(product_agent_ids) == 1:
        return product_agent_ids[0]
    
    # There is still a tie. Check open cases
    
    open_cases = get_cases(agent_ids=product_agent_ids, statuses=["Open"])
    
    open_case_agent_ids = get_agents_with_min_cases(open_cases)
    
    if len(open_case_agent_ids) == 0:
        return None
    elif len(open_case_agent_ids) == 1:
        return open_case_agent_ids[0]
    
def get_agent_by_handle_time(extrema, n_cases, end_date=None, period=None, interval_count=None, period_name=None, year=None):
    """
    TODO: delete
    Identifies the agent with the specified handle time (minimum or maximum) 
    for the given time period among those who managed more than a specified number of cases.
    """
    
    # get start and end_date
    
    if end_date is not None:
        start_date = get_start_date(end_date, period, interval_count)
    else:
        start_end_date = get_period(period_name, year)
        start_date = start_end_date['start_date']
        end_date = start_end_date['end_date']
    
    agent_handled_cases = get_agent_handled_cases_by_period(start_date, end_date)

    qualified_agent_ids = get_qualified_agent_ids_by_case_count(agent_handled_cases, n_cases)

    non_transferred_case_ids = get_non_transferred_case_ids(start_date, end_date)
    
    if not qualified_agent_ids:
        return None
    
    cases = get_cases(start_date=start_date, end_date=end_date, agent_ids=qualified_agent_ids, case_ids=non_transferred_case_ids, statuses=["Closed"])
    
    agent_handle_times = calculate_average_handle_time(cases)
    if extrema == 'min':
        return find_id_with_min_value(agent_handle_times)
    else:
        return find_id_with_max_value(agent_handle_times)
    
def get_agent_by_transfer_time(extrema, n_cases, end_date=None, period=None, interval_count=None, period_name=None, year=None):
    """
    Todo: delete
    Identifies the agent with the specified transfer time (minimum or maximum) 
    for the given time period among those who managed more than a specified number of cases.
    """
    if end_date is not None:
        start_date = get_start_date(end_date, period, interval_count)
    else:
        start_end_date = get_period(period_name, year)
        start_date = start_end_date['start_date']
        end_date = start_end_date['end_date']
    
    
    agent_handled_cases = get_agent_handled_cases_by_period(start_date, end_date)
    
    qualified_agent_ids = get_qualified_agent_ids_by_case_count(agent_handled_cases, n_cases)
    
    
    if not qualified_agent_ids:
      return None
    agent_transfer_counts = get_agent_trasferred_cases_by_period(start_date, end_date, qualified_agent_ids)
    
    if not agent_transfer_counts:
        return None
    
    if extrema == 'min':
        return find_id_with_min_value(agent_transfer_counts)
    else:
        return find_id_with_max_value(agent_transfer_counts)        
    
    
# # named entity disambiguation

if True:
    # {"metadata": {"today": "2021-12-27", "task": "named_entity_disambiguation", "customer_id": "003Ws000004G1ttIAC"}, "query": "Show me the high-speed racing suit I purchased last month", "answer": [null]}
    assert get_disambiguiated_named_entity("racing suit", "003Ws000004G1ttIAC", today_date="2021-12-27T00:00:00Z", period="month", interval_count=1) == None

    # {"metadata": {"today": "2021-03-22", "task": "named_entity_disambiguation", "customer_id": "003Ws000004FzfCIAS"}, "query": "Can you display the professional football cleats I purchased last week?", "answer": [null]}
    assert get_disambiguiated_named_entity("football cleats", "003Ws000004FzfCIAS", today_date="2021-03-22T00:00:00Z", period="week", interval_count=1) == None

    # {"metadata": {"today": "2020-09-10", "task": "named_entity_disambiguation", "customer_id": "003Ws000004FvN4IAK"}, "query": "Display the speed training jump rope I purchased one week ago", "answer": ["01tWs000002wROTIA2"]}
    assert get_disambiguiated_named_entity("rope", "003Ws000004FvN4IAK", today_date="2020-09-10T00:00:00Z", period="week", interval_count=1) == "01tWs000002wROTIA2"

    # {"metadata": {"today": "2020-03-22", "task": "named_entity_disambiguation", "customer_id": "003Ws000004G1c9IAC"}, "query": "Display the Eco-Friendly Yoga Leggings that I purchased a week ago", "answer": ["01tWs000002wRUvIAM"]}
    assert get_disambiguiated_named_entity("Yoga", "003Ws000004G1c9IAC", today_date="2020-03-22T00:00:00Z", period="week", interval_count=1) == "01tWs000002wRUvIAM"

    # {"metadata": {"today": "2021-03-30", "task": "named_entity_disambiguation", "customer_id": "003Ws000004G01mIAC"}, "query": "Can you display the light running shorts I purchased fourteen days ago?", "answer": [null]}
    assert get_disambiguiated_named_entity("running shorts", "003Ws000004G01mIAC", today_date="2021-03-30T00:00:00Z", period="day", interval_count=14) == None

# Test

# Case Routing
if True:
    # {"metadata": {"task": "case_routing", "case_subject": "Wrong Size Delivered - ProGrip Tennis Racket", "case_description": "I recently purchased a ProGrip Tennis Racket from your website, but the size does not match the chart provided online. I ordered a size L based on the measurements, but the racket I received feels much smaller. It's really disappointing as I can't use it for my matches. Could you please assist me with an exchange or return?", "issue_id": "a1MWs0000012u0jMAA", "product_id": "01tWs000002wVogIAE"}, "query": "Who is the most suitable agent for this case?", "answer": ["005Ws000001xYl3IAE"]}
    assert get_best_assigned_agent("a1MWs0000012u0jMAA", "01tWs000002wVogIAE") == "005Ws000001xYl3IAE"

    # {"metadata": {"task": "case_routing", "case_subject": "Received Wrong Item", "case_description": "I ordered the Dynamic Yoga Pants but received a completely different item. I need this resolved as soon as possible and request an immediate exchange for the correct product.", "issue_id": "a1MWs0000012u7BMAQ", "product_id": "01tWs000002wRpwIAE"}, "query": "Who is the most suitable agent for this case?", "answer": ["005Ws000001xZvdIAE"]}
    assert get_best_assigned_agent("a1MWs0000012u7BMAQ", "01tWs000002wRpwIAE") == "005Ws000001xZvdIAE"

    # {"metadata": {"task": "case_routing", "case_subject": "Issue with the size chart for Urban Lifestyle Sneakers", "case_description": "I recently purchased a pair of Urban Lifestyle Sneakers and found that the size chart on your website does not match the actual product size. The sneakers are much smaller than expected, causing discomfort when worn. I've double-checked my order and confirmed that I followed the size chart correctly. Please advise on how this can be resolved or if a replacement can be arranged.", "issue_id": "a1MWs0000012u0jMAA", "product_id": "01tWs000002wRt7IAE"}, "query": "Which agent would be the most suitable for this case?", "answer": ["005Ws000001xYl3IAE"]}
    assert get_best_assigned_agent("a1MWs0000012u0jMAA", "01tWs000002wRt7IAE") == "005Ws000001xYl3IAE"

    # {"metadata": {"task": "case_routing", "case_subject": "Mismatch between advertised and actual size", "case_description": "I ordered the Pro Basketball Rebounder based on the size chart provided on your website. However, when the product arrived, it was significantly smaller than what was advertised. The dimensions do not match those listed online. This size discrepancy is affecting its usability and my training sessions.", "issue_id": "a1MWs0000012u0jMAA", "product_id": "01tWs000002wURCIA2"}, "query": "Who is the most suitable agent for this case?", "answer": ["005Ws000001xYl3IAE"]}
    assert get_best_assigned_agent("a1MWs0000012u0jMAA", "01tWs000002wURCIA2") == "005Ws000001xYl3IAE"

    # {"metadata": {"task": "case_routing", "case_subject": "Size Mismatch Issue with WaveRider Swim Cap", "case_description": "I recently purchased the WaveRider Swim Cap, but the size chart provided on the website does not accurately represent the actual product size. The cap I received is too small and doesn't fit comfortably. I followed the size guide, but it seems to be incorrect. Please advise on what I should do next.", "issue_id": "a1MWs0000012u0jMAA", "product_id": "01tWs000002wUhJIAU"}, "query": "Who is the most suitable agent for this case?", "answer": ["005Ws000001xYl3IAE"]}
    assert get_best_assigned_agent("a1MWs0000012u0jMAA", "01tWs000002wUhJIAU") == "005Ws000001xYl3IAE"

    # {"metadata": {"task": "case_routing", "case_subject": "Incorrect Item Received - Urgent Exchange Needed", "case_description": "I recently ordered the Zen Zone Yoga Mat but received a completely different item instead. I need an immediate exchange as I specifically purchased this non-slip mat with extra cushioning for my yoga practice.", "issue_id": "a1MWs0000012u7BMAQ", "product_id": "01tWs000002wRLGIA2"}, "query": "Which agent is most suitable for this case?", "answer": ["005Ws000001xZvdIAE"]}
    assert get_best_assigned_agent("a1MWs0000012u7BMAQ", "01tWs000002wRLGIA2") == "005Ws000001xZvdIAE"

    # {"metadata": {"task": "case_routing", "case_subject": "Received Incorrect Item - Urgent Exchange Needed", "case_description": "I recently placed an order for the Women's High-Performance Jacket, but I received a completely different item instead. I urgently need an exchange for the correct item as soon as possible. Please assist me with this issue promptly.", "issue_id": "a1MWs0000012u7BMAQ", "product_id": "01tWs000002wTRtIAM"}, "query": "Who is the most suitable agent to assign to this case?", "answer": ["005Ws000001xZvdIAE"]}
    assert get_best_assigned_agent("a1MWs0000012u7BMAQ", "01tWs000002wTRtIAM") == "005Ws000001xZvdIAE"

    # {"metadata": {"task": "case_routing", "case_subject": "Size Mismatch for Women's Sporty Capri Leggings", "case_description": "I recently purchased the Women's Sporty Capri Leggings in size Medium, but they do not fit as expected. The size chart on the website indicated that Medium would be my size, but the leggings are too tight and uncomfortable. Please assist in resolving this size mismatch issue.", "issue_id": "a1MWs0000012u0jMAA", "product_id": "01tWs000002wNRKIA2"}, "query": "Who is the most suitable agent for this case?", "answer": ["005Ws000001xYl3IAE"]}
    assert get_best_assigned_agent("a1MWs0000012u0jMAA", "01tWs000002wNRKIA2") == "005Ws000001xYl3IAE"

    # {"metadata": {"task": "case_routing", "case_subject": "Delayed Delivery of Tracker Smartwatch", "case_description": "I ordered the Tracker Smartwatch expecting it to arrive within the promised 3-5 days, but it has been two weeks and I still haven't received it. This delay is frustrating, especially since I specifically needed it for an upcoming event. Please look into this and provide an update on my order status.", "issue_id": "a1MWs0000012u2LMAQ", "product_id": "01tWs000002wRjRIAU"}, "query": "Who is the optimal agent to allocate to this case?", "answer": ["005Ws000001xaoTIAQ"]}
    assert get_best_assigned_agent("a1MWs0000012u2LMAQ", "01tWs000002wRjRIAU") == "005Ws000001xaoTIAQ"

    # {"metadata": {"task": "case_routing", "case_subject": "Incorrect Item Received for Pro Swim Cap", "case_description": "I recently ordered a Pro Swim Cap, but I received a different item instead. I need an immediate exchange to get the correct product, as the Pro Swim Cap is essential for my upcoming swim meet.", "issue_id": "a1MWs0000012u7BMAQ", "product_id": "01tWs000002wQXHIA2"}, "query": "Who is the most suitable agent for this case?", "answer": ["005Ws000001xZvdIAE"]}
    assert get_best_assigned_agent("a1MWs0000012u7BMAQ", "01tWs000002wQXHIA2") == "005Ws000001xZvdIAE"




# Best region

if True:
    # {"metadata": {"today": "2024-06-04", "task": "best_region_identification"}, "query": "Which states had the quickest case closures in October 2021?", "answer": ["CO"]}
    assert get_best_region(period_name="October", year=2021) == "CO"

    # {"metadata": {"today": "2023-05-24", "task": "best_region_identification"}, "query": "During the second quarter of 2020, in which states were cases closed the fastest?", "answer": ["NY"]}
    assert get_best_region(period_name="Q2", year=2020) == "NY"

    # {"metadata": {"today": "2022-06-01", "task": "best_region_identification"}, "query": "What states have the quickest case closures in the past four weeks?", "answer": ["OR"]}
    assert get_best_region(end_date="2022-06-01T00:00:00Z", period="week", interval_count=4) == "OR"

    # {"metadata": {"today": "2024-08-16", "task": "best_region_identification"}, "query": "Which states have the quickest case closures over the past 6 months?", "answer": ["CO"]}
    assert get_best_region(end_date="2024-08-16T00:00:00Z", period="month", interval_count=6) == "CO"

    # {"metadata": {"today": "2025-10-03", "task": "best_region_identification"}, "query": "Which states had the fastest case closure in September 2022?", "answer": ["GA"]}
    assert get_best_region(period_name="September", year=2022) == "GA"

    # {"metadata": {"today": "2021-06-20", "task": "best_region_identification"}, "query": "Which states have the quickest case closures in the past 2 weeks?", "answer": ["WI"]}
    assert get_best_region(end_date="2021-06-20T00:00:00Z", period="week", interval_count=2) == "WI"

    # {"metadata": {"today": "2023-01-19", "task": "best_region_identification"}, "query": "Which states had the quickest case closures in the past 5 quarters?", "answer": ["MI"]}
    assert get_best_region(end_date="2023-01-19T00:00:00Z", period="quarter", interval_count=5) == "MI"
    # {"metadata": {"today": "2023-05-27", "task": "best_region_identification"}, "query": "Which states had the quickest case closures in Q2 of 2022?", "answer": ["TN"]}
    assert get_best_region(period_name="Q2", year=2022) == "TN"
    # {"metadata": {"today": "2020-04-05", "task": "best_region_identification"}, "query": "Which states have the quickest case closures in the past two weeks?", "answer": ["CA"]}
    assert get_best_region(end_date="2020-04-05T00:00:00Z", period="week", interval_count=2) == "CA"
    # {"metadata": {"today": "2022-01-02", "task": "best_region_identification"}, "query": "Which states have the quickest case closures in the past 4 months?", "answer": ["NC"]}
    assert get_best_region(end_date="2022-01-02T00:00:00Z", period="month", interval_count=4) == "NC"
    # {"metadata": {"today": "2023-08-04", "task": "best_region_identification"}, "query": "Which states had the quickest case closures in Q2 of 2023?", "answer": ["FL"]}
    assert get_best_region(period_name="Q2", year=2023) == "FL"

# Seaonality

if True:
    # {"metadata": {"today": "2021-03-23", "task": "seasonality_identification", "product_id": "01tWs000002wRt7IAE"}, "query": "Were there any months in the past 10 months where the number of cases received for Urban Lifestyle Sneakers was significantly higher than in other months?", "answer": ["December"]}
    assert get_most_issue_month("01tWs000002wRt7IAE", end_date="2021-03-23T00:00:00Z", period="month", interval_count=10) == "December"

    # {"metadata": {"today": "2021-11-03", "task": "seasonality_identification", "product_id": "01tWs000002wSFhIAM"}, "query": "Is there a specific month in the past 11 months when the number of Flex Yoga Mat cases was significantly higher than in others?", "answer": ["March"]}
    assert get_most_issue_month("01tWs000002wSFhIAM", end_date="2021-11-03T00:00:00Z", period="month", interval_count=11) == "March"

    # {"metadata": {"today": "2022-05-25", "task": "seasonality_identification", "product_id": "01tWs000002wQXHIA2"}, "query": "Is there a specific month in the last 7 months where the Pro Swim Cap cases received were significantly higher compared to other months?", "answer": ["March"]}
    assert get_most_issue_month("01tWs000002wQXHIA2", end_date="2022-05-25T00:00:00Z", period="month", interval_count=7) == "March"

    # {"metadata": {"today": "2024-03-23", "task": "seasonality_identification", "product_id": "01tWs000002wSFiIAM"}, "query": "In the past 9 months, is there a particular month where the volume of cases for Impact Basketball Shoes greatly exceeds that of other months?", "answer": ["November"]}
    assert get_most_issue_month("01tWs000002wSFiIAM", end_date="2024-03-23T00:00:00Z", period="month", interval_count=9) == "November"

    # {"metadata": {"today": "2021-05-02", "task": "seasonality_identification", "product_id": "01tWs000002wSKXIA2"}, "query": "Was there a month where the number of cases received for the Ultimate Yoga Strap was significantly higher compared to other months in the past 11 months?", "answer": ["December"]}
    assert get_most_issue_month("01tWs000002wSKXIA2", end_date="2021-05-02T00:00:00Z", period="month", interval_count=11) == "December"

    # {"metadata": {"today": "2022-06-16", "task": "seasonality_identification", "product_id": "01tWs000002wR0IIAU"}, "query": "In the past 8 months, is there a specific month where the number of cases received for the Versatile Fitness Mat is significantly higher than the others?", "answer": ["March"]}
    assert get_most_issue_month("01tWs000002wR0IIAU", end_date="2022-06-16T00:00:00Z", period="month", interval_count=8) == "March"

    # {"metadata": {"today": "2022-10-14", "task": "seasonality_identification", "product_id": "01tWs000002wTi1IAE"}, "query": "Is there a specific month in the past 7 months where the number of cases for Flex Fit Yoga Capris was significantly higher than the other months?", "answer": ["September"]}
    assert get_most_issue_month("01tWs000002wTi1IAE", end_date="2022-10-14T00:00:00Z", period="month", interval_count=7) == "September"

    # {"metadata": {"today": "2020-05-26", "task": "seasonality_identification", "product_id": "01tWs000002wRujIAE"}, "query": "Is there a month in the past 7 months where we received significantly more Cycling Thermal Jacket cases than other months?", "answer": ["March"]}
    assert get_most_issue_month("01tWs000002wRujIAE", end_date="2020-05-26T00:00:00Z", period="month", interval_count=7) == "March"
    # {"metadata": {"today": "2022-10-09", "task": "seasonality_identification", "product_id": "01tWs000002wQXGIA2"}, "query": "Is there any month in the past 8 months where we've received significantly more cases for the All-Around Yoga Tank compared to other months?", "answer": ["March"]}
    assert get_most_issue_month("01tWs000002wQXGIA2", end_date="2022-10-09T00:00:00Z", period="month", interval_count=8) == "March"


# Issue count
if True:
    # {"metadata": {"today": "2023-04-29", "task": "top_issue_identification", "product_id": "01tWs000002wSKYIA2"}, "query": "What has been the most frequently reported problem with Women's Trail Running Shorts over the past 6 quarters?", "answer": ["a1MWs0000012u0jMAA"]}
    assert get_top_issue_by_product("01tWs000002wSKYIA2", end_date="2023-04-29T00:00:00Z", period="quarter", interval_count=6) == "a1MWs0000012u0jMAA"

    # {"metadata": {"today": "2020-04-12", "task": "top_issue_identification", "product_id": "01tWs000002wWG7IAM"}, "query": "What was the most frequent problem with High-Performance Golf Hats during the summer of 2020?", "answer": [null]}
    assert get_top_issue_by_product("01tWs000002wWG7IAM", period_name="Summer", year=2020) == None

    # {"metadata": {"today": "2022-12-18", "task": "top_issue_identification", "product_id": "01tWs000002wNvzIAE"}, "query": "What was the most frequent problem encountered with the Enduro Training Ladder during the summer of 2020?", "answer": [null]}
    assert get_top_issue_by_product("01tWs000002wNvzIAE", period_name="Summer", year=2020) == None

    # {"metadata": {"today": "2022-08-28", "task": "top_issue_identification", "product_id": "01tWs000002wSNlIAM"}, "query": "What was the most frequent problem with Trail Running Shoes in the fourth quarter of 2022?", "answer": ["a1MWs0000012tz7MAA"]}
    assert get_top_issue_by_product("01tWs000002wSNlIAM", period_name="Q4", year=2022) == "a1MWs0000012tz7MAA"

    # {"metadata": {"today": "2023-12-12", "task": "top_issue_identification", "product_id": "01tWs000002wRedIAE"}, "query": "What is the most frequent problem with Aquatic Resistance Gloves in the past 5 months?", "answer": [null]}
    assert get_top_issue_by_product("01tWs000002wRedIAE", end_date="2023-12-12T00:00:00Z", period="month", interval_count=5) == None

    # {"metadata": {"today": "2022-08-09", "task": "top_issue_identification", "product_id": "01tWs000002wUUPIA2"}, "query": "What has been the most frequent problem with the Smart Sports Bra in the past three quarters?", "answer": ["a1MWs0000012u7BMAQ"]}
    assert get_top_issue_by_product("01tWs000002wUUPIA2", end_date="2022-08-09T00:00:00Z", period="quarter", interval_count=3) == "a1MWs0000012u7BMAQ"

    # {"metadata": {"today": "2024-06-25", "task": "top_issue_identification", "product_id": "01tWs000002wTLRIA2"}, "query": "What is the most frequent problem with Functional Training Kettlebell in Fall 2022?", "answer": ["a1MWs0000012txVMAQ"]}
    assert get_top_issue_by_product("01tWs000002wTLRIA2", period_name="Fall", year=2022) == "a1MWs0000012txVMAQ"

# Handle Time

if True:
  # {"metadata": {"today": "2022-08-17", "task": "handle_time"}, "query": "Over the past two months, which agent had the highest average handle time for cases they managed?", "answer": ["005Ws000001xZZ3IAM"]}
  assert get_agent_by_handle_time(extrema="max", n_cases=0, end_date="2022-08-17T00:00:00Z", period="month", interval_count=2) == "005Ws000001xZZ3IAM"
  # {"metadata": {"today": "2020-11-07", "task": "handle_time"}, "query": "In the Winter of 2020, find the agent who resolved more than two cases and had the highest average handle time.", "answer": ["005Ws000001xaBlIAI"]}
  assert get_agent_by_handle_time(extrema="max", n_cases=2, period_name="Winter", year=2020) == "005Ws000001xaBlIAI"
  # {"metadata": {"today": "2020-01-30", "task": "handle_time"}, "query": "Which agent had the lowest average handle time over the past 6 quarters for agents managing more than 3 cases?", "answer": [null]}
  assert get_agent_by_handle_time(extrema="min", n_cases=3, end_date="2020-01-30T00:00:00Z", period="quarter", interval_count=6) == None

  # {"metadata": {"today": "2023-06-25", "task": "handle_time"}, "query": "For Q1 2023, find the agent who dealt with more than one case and had the longest handling time.", "answer": ["005Ws000001xZu1IAE"]}
  assert get_agent_by_handle_time(extrema="max", n_cases=1, period_name="Q1", year=2023) == "005Ws000001xZu1IAE"

  # {"metadata": {"today": "2021-10-31", "task": "handle_time"}, "query": "Identify the agent with the shortest handle time over the past 5 weeks among those who managed cases.", "answer": ["005Ws000001xZvdIAE"]}
  assert get_agent_by_handle_time(extrema="min", n_cases=0, end_date="2021-10-31T00:00:00Z", period="week", interval_count=5) == "005Ws000001xZvdIAE"

  # {"metadata": {"today": "2022-01-06", "task": "handle_time"}, "query": "Identify the agent with the lowest handle time over the past 4 weeks among those who managed more than one case.", "answer": ["005Ws000001xaRtIAI"]}
  assert get_agent_by_handle_time(extrema="min", n_cases=1, end_date="2022-01-06T00:00:00Z", period="week", interval_count=4) == "005Ws000001xaRtIAI"

  # {"metadata": {"today": "2023-09-04", "task": "handle_time"}, "query": "Which agent had the longest average handle time during the last two quarters for those handling more than zero cases?", "answer": ["005Ws000001xTbjIAE"]}
  assert get_agent_by_handle_time(extrema="max", n_cases=0, end_date="2023-09-04T00:00:00Z", period="quarter", interval_count=2) == "005Ws000001xTbjIAE"

  # {"metadata": {"today": "2021-08-27", "task": "handle_time"}, "query": "During the summer of 2021, find the agent who dealt with more than two cases and had the highest average handle time.", "answer": ["005Ws000001xYl3IAE"]}
  assert get_agent_by_handle_time(extrema="max", n_cases=2, period_name="Summer", year=2021) == "005Ws000001xYl3IAE"

  # {"metadata": {"today": "2022-11-30", "task": "handle_time"}, "query": "In May 2022, find the agent with the shortest handle time who managed cases.", "answer": ["005Ws000001xZCTIA2"]}
  assert get_agent_by_handle_time(extrema="min", n_cases=0, period_name="May", year=2022) == "005Ws000001xZCTIA2"

  # {"metadata": {"today": "2021-12-05", "task": "handle_time"}, "query": "Which agent had the lowest average handle time over the past 4 months for those managing more than 2 cases?", "answer": ["005Ws000001xYgDIAU"]}
  assert get_agent_by_handle_time(extrema="min", n_cases=2, end_date="2021-12-05T00:00:00Z", period="month", interval_count=4) == "005Ws000001xYgDIAU"

  # {"metadata": {"today": "2022-04-20", "task": "handle_time"}, "query": "Identify the agent with the shortest handle time over the last two weeks among those who handled more than two cases.", "answer": [null]}
  assert get_agent_by_handle_time(extrema="min", n_cases=2, end_date="2022-04-20T00:00:00Z", period="week", interval_count=2) == None

# Transfer Time

if True:
  # {"metadata": {"today": "2022-02-19", "task": "transfer_time"}, "query": "Identify the agent with the highest number of transfers over the last 6 quarters among those who have managed more than 2 cases.", "answer": ["005Ws000001xYxxIAE"]}
  assert get_agent_by_transfer_time(extrema="max", n_cases=2, end_date="2022-02-19T00:00:00Z", period="quarter", interval_count=6) == "005Ws000001xYxxIAE"

  # {"metadata": {"today": "2020-05-03", "task": "transfer_time"}, "query": "Which agent had the lowest average transfer times over the last 4 quarters among those managing more than 3 cases?", "answer": ["005Ws000001xZvdIAE"]}
  assert get_agent_by_transfer_time(extrema="min", n_cases=3, end_date="2020-05-03T00:00:00Z", period="quarter", interval_count=4) == "005Ws000001xZvdIAE"

  # {"metadata": {"today": "2020-07-05", "task": "transfer_time"}, "query": "Which agent had the highest average transfer times over the past 6 weeks among those handling more than 1 case?", "answer": ["005Ws000001xaoTIAQ"]}
  assert get_agent_by_transfer_time(extrema="max", n_cases=1, end_date="2020-07-05T00:00:00Z", period="week", interval_count=6) == "005Ws000001xaoTIAQ"

  # {"metadata": {"today": "2022-09-24", "task": "transfer_time"}, "query": "In the last 4 quarters, which agent had the highest average transfer time among those who handled over 3 cases?", "answer": ["005Ws000001xYxxIAE"]}
  assert get_agent_by_transfer_time(extrema="max", n_cases=3, end_date="2022-09-24T00:00:00Z", period="quarter", interval_count=4) == "005Ws000001xYxxIAE"

  # {"metadata": {"today": "2020-02-24", "task": "transfer_time"}, "query": "In the past 6 weeks, which agent had the highest average transfer times for agents managing more than 3 cases?", "answer": [null]}
  assert get_agent_by_transfer_time(extrema="max", n_cases=3, end_date="2020-02-24T00:00:00Z", period="week", interval_count=6) == None


  # {"metadata": {"today": "2021-01-24", "task": "transfer_time"}, "query": "Find the agent in February 2021 who handled over 3 cases with the fewest number of transfers.", "answer": [null]}
  assert get_agent_by_transfer_time(extrema="min", n_cases=3, period_name="February", year=2021) == None


  # {"metadata": {"today": "2021-09-21", "task": "transfer_time"}, "query": "Which agent had the lowest average transfer times over the past 4 weeks for those handling more than 0 cases?", "answer": ["005Ws000001xatJIAQ"]}
  assert get_agent_by_transfer_time(extrema="min", n_cases=0, end_date="2021-09-21T00:00:00Z", period="week", interval_count=4) == "005Ws000001xatJIAQ"

  # {"metadata": {"today": "2024-03-04", "task": "transfer_time"}, "query": "In Spring 2023, find the agent with over two cases managed who had the lowest transfer count.", "answer": ["005Ws000001xa0TIAQ"]}
  assert get_agent_by_transfer_time(extrema="min", n_cases=2, period_name="Spring", year=2023) == "005Ws000001xa0TIAQ"

  # {"metadata": {"today": "2023-11-05", "task": "transfer_time"}, "query": "In the last 6 months, identify the agent with the fewest transfer times among those who handled more than 2 cases.", "answer": [null]}
  assert get_agent_by_transfer_time(extrema="min", n_cases=2, end_date="2023-11-05T00:00:00Z", period="month", interval_count=6) == None

  # {"metadata": {"today": "2023-12-22", "task": "transfer_time"}, "query": "In the past three weeks, which agent had the lowest average transfer times among those handling more than one case?", "answer": ["005Ws000001xZXRIA2"]}
  assert get_agent_by_transfer_time(extrema="min", n_cases=1, end_date="2023-12-22T00:00:00Z", period="week", interval_count=3) == "005Ws000001xZXRIA2"


