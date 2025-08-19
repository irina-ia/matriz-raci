from google.cloud import bigquery
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import numpy as np
import os
import re
import streamlit as st
import subprocess
from tqdm import tqdm
import pandas as pd
# from plotly import colors
from plotly import graph_objects as go
from itertools import product
import pytz
from metria import utils, credentials
from typing import Optional

### FORMATO DEL DASHBOARD ###

# Maximize the width of the app
st.set_page_config(layout="wide")

# Custom CSS to adjust margins/padding
custom_css = """
    <style>
        /* Remove padding and margin from the main content area */
        .main .block-container {
            padding-top: 1.5rem; /* Adjust top padding */
            padding-right: 5rem; /* Adjust right padding */
            padding-left: 5rem; /* Adjust left padding */
            padding-bottom: 2rem; /* Adjust bottom padding */
        }
    </style>
"""

# Inject custom CSS
st.markdown(custom_css, unsafe_allow_html=True)

# Ruta de los archivos del script a ejecutar, y titulo para reportes
origin, folder, project = 'Reporting', 'streamlit_analytics_funnel', 'streamlit_app'
origin, folder = 'Reporting', 'streamlit_analytics_funnel'
# Reporting/streamlit_analytics_funnel/storage/df_users_funnel.pkl

# Load the dataframe if it doesn't exist
path_graphs = utils.script_path([origin, folder, 'storage', 'df_users_funnel.pkl'])
etl_command = ['python', utils.script_path([origin, folder, 'etl_funnel_script.py'])]

# Order of each plan by country
ordered_plans = {'Chile': ['Zapping Full', 'Zapping Lite+', 'Zapping Lite'],
                 'Brasil': ['Zapping Full', 'Zapping Lite+', 'Zapping Lite'],
                 'Peru': ['Plan Plus', 'Fútbol Perú', 'Nacional'],
                 'Ecuador': ['Plan Futbol', 'Full']}

with st.sidebar:
    # st.write('## Configuración')
    page = st.selectbox('Página', ['Adquisición', 'Churn', 'Flujo', 'Eventos'])
    plan_type_mapper = {'Base': 1, 'Addon': 0}
    mapper_b2b = {'B2B': 1, 'B2C': 0}

    def basic_sidebar(mapper_b2b=mapper_b2b,
                      plan_type_mapper=plan_type_mapper):
        
        """ Function to create the basic sidebar for the dashboard
        Args:
            df_graphs (pd.DataFrame): Dataframe with the information to filter
            mapper_b2b (dict): Dictionary with the mapping of B2B and B2C
            plan_type_mapper (dict): Dictionary with the mapping of Base and Addon
        Returns:
            tuple: Tuple with the selected countries, plan status, plan type and is B2B
        """

        try:
            df_graphs = pd.read_pickle(path_graphs)

        except Exception as e:
            subprocess.run(etl_command)
            df_graphs = pd.read_pickle(path_graphs)

        # Translate the timestamp from UTC to America/Santiago and to a string
        last_update = df_graphs['created'].dt.tz_convert('America/Santiago').max()
        # last_update = datetime.strptime('2024-06-21 23:59:59', '%Y-%m-%d %H:%M:%S')

        st.write(f'Última actualización: {last_update:%Y-%m-%d %H:%M}')

        button_update = st.button('Click acá para actualizar los datos')

        if button_update:
            # Delete pickle file in path
            subprocess.run(etl_command)

        # Otras opciones para el sidebar
        countries = st.multiselect('Países', ['Chile', 'Brasil', 'Peru', 'Ecuador'],
                                default=['Chile'], placeholder='Seleccione el o los paises a graficar')
        
        plan_status = st.multiselect('Plan Status', ['active', 'trial', 'inactive', 'demo'],
                                    default=['active', 'trial'],
                                    placeholder='Seleccione el o los status de plan a graficar')
        
        plan_type = st.multiselect('Plan Type', plan_type_mapper.keys(),
                                    default='Base', placeholder='Seleccione si considera addons')
        
        # Dictionary with 
        is_b2b = st.multiselect('Series', mapper_b2b.keys(),
                                default=['B2C'], placeholder='Seleccione si es B2B o B2C')
        
        # Coupons to filter the dataframe
        coupons = st.multiselect('Cupones', df_graphs['coupon_name'].unique(),
                                 placeholder='Seleccione el cupón')
        
        # Give the dates directly and transform them to a datetime object
        # last_update = st.date_input('Fecha', datetime.now())# - timedelta(days=1))
        # last_update = datetime.combine(last_update, datetime.now().time())
        
        if len(coupons) == 0:
            coupons = df_graphs['coupon_name'].unique()
        
        return countries, plan_status, plan_type, is_b2b, coupons, last_update, df_graphs

    if page == 'Adquisición':
        countries, plan_status, plan_type, is_b2b, coupons, last_update, df_graphs = basic_sidebar()

    if page == 'Churn':
        countries, plan_status, plan_type, is_b2b, coupons, last_update, df_graphs = basic_sidebar()
        methods = st.multiselect('Método', ['Cancel Scheduled', 'Cancelled'],
                                default='Cancel Scheduled', placeholder='Seleccione el método')

        # Number of Months for the XMRR
        months_subscribed = st.slider('XMRR', 3, 12, 1)

    if page == 'Flujo':
        countries = st.multiselect('Países', ['Chile', 'Brasil', 'Peru', 'Ecuador'],
                                   default=['Brasil'], 
                                   placeholder='Seleccione el o los paises a graficar')
        
        date_aggregation = st.selectbox('Agregación de fechas', ['Días', 'Semanas',
                                                                 'Meses', 'Años'],
                                        index=2, key='date_aggregation')
        
        max_bars = st.slider('Barras a visualizar', 1, 10, 5)

        df_graphs, last_update = None, None

    if page == 'Eventos':
        # Fecha de inicio y de término
        event_start_date = st.date_input('Fecha de inicio')
        event_start_time = st.time_input('Hora de inicio')
        event_end_date = st.date_input('Fecha de término')
        event_end_time = st.time_input('Hora de término')

        # Fecha en que se anunció el evento
        event_announcement = st.date_input('Fecha de anuncio')

        # Insert channel manually and freely
        event_channel = st.text_input('Canal')

        # Time in minutes for the event
        time_connected = st.number_input('Tiempo de visualización', min_value=0, max_value=1440, value=15)

        # País
        event_country = st.selectbox('País', ['Chile', 'Brasil', 'Peru'], index=1)

        # Create a button to update the data
        button_update = st.button('Click acá para ejecutar la consulta')#, key='button_update')

        df_graphs, last_update = None, None


### FILTERING THE MAIN DATAFRAME
def prepare_main(df_graphs: Optional[pd.DataFrame]=df_graphs):
    if df_graphs is None:
        return None
    
    # Para XMRR
    df_xmrr = df_graphs.copy(deep=True)

    # Filter the dataframe by the selected countries
    df_graphs = df_graphs[(df_graphs['countryName'].isin(countries)) &
                            (df_graphs['planStatus'].isin(plan_status)) &
                            (df_graphs['isB2B'].isin([mapper_b2b[elem] 
                                                        for elem in is_b2b])) &
                            (df_graphs['main'].isin([plan_type_mapper[plan]
                                                    for plan in plan_type])) &
                            (df_graphs['created'].dt.date <= last_update.date()) &
                            #(df_graphs['acquisition'].isin(coupons)) &
                            (df_graphs['packageID']>70)].copy(deep=True)

    # Filter out test on this DataFrame
    test_terms = ('prueba', 'test', r'blueway.cl')

    for term in test_terms:
        df_graphs = df_graphs[(df_graphs['email'].str.contains(term) == False) & 
                              (df_graphs['first_name'].str.contains(term) == False) &
                              (df_graphs['last_name'].str.contains(term) == False)].copy(deep=True)

    # Para sacar los usuarios únicos se debe restar los PPV de los usuarios duplicados
    # unique_users = len(df_graphs['user_id'].unique())

    ### Adding time column
    # Transform columns from UTC to America/Santiago
    cols = ['extraction_dttm', 'created', 'updated']

    for col in cols:
        if (df_graphs[col].dt.tz is None):
            # Alto ahí! Esto puede parecer un error, pero controla por días de cambio de horario
            df_graphs[col] = df_graphs[col].dt.tz_localize('UTC')\
                .dt.tz_convert('America/Santiago')
        else:
            df_graphs[col] = df_graphs[col].dt.tz_convert('America/Santiago')

    # Find the position of created column
    created_position = df_graphs.columns.get_loc('created')
    df_graphs.insert(loc=created_position+1, column='created_time',
                    value=df_graphs['created'].dt.strftime('%H:%M'))

    df_graphs['created_time'] = df_graphs['created_time'].str\
        .replace(r':[0-9]+', r':00', regex=True)

    return df_graphs, df_xmrr, last_update #unique_users, 



### CREAMOS EL PRIMER GRÁFICO
#@st.cache_data
def prepare_fig01():
    # Add a plotly graph
    fig1 = go.Figure()

    df_periodos = df_graphs.copy(deep=True)
    mapper_series = {'Today': 'today', 'Yesterday': 'yesterday',
                    'Last 7 days': 'last07', 'Last 30 days': 'last30'}

    for i, serie in enumerate(mapper_series.keys(), start=1):
        serie_code = mapper_series[serie]
        df_periodos.insert(loc=2+i, column=f'serie_{serie_code}', value=None)

    # DataFrame para el día de hoy
    df_periodos.loc[df_periodos['created'].dt.date == last_update.date(), 'serie_today'] = 1

    # DataFrame para el día de ayer
    yesterday = last_update.date() - timedelta(days=1)
    df_periodos.loc[df_periodos['created'].dt.date == yesterday, 'serie_yesterday'] = 1

    # DataFrame para los últimos 7 días
    df_periodos.loc[(df_periodos['created'].dt.date > (yesterday - timedelta(days=7))) &
                (df_periodos['created'].dt.date <= yesterday), 'serie_last07'] = 1

    # DataFrame para los últimos 30 días
    df_periodos.loc[(df_periodos['created'].dt.date > (yesterday - timedelta(days=30))) &
                (df_periodos['created'].dt.date <= yesterday), 'serie_last30'] = 1

    # Eliminamos las filas que no tienen serie
    list_index = []
    for serie_value in mapper_series.values():
        list_index.extend(df_periodos[~df_periodos[f'serie_{serie_value}'].isnull()].index)

    # Filtramos el dataframe y agregamos el tiempo de creación
    df_periodos = df_periodos[df_periodos.index.isin(list_index)].copy(deep=True)

    # Define graph colors using the pinkly colors
    dict_colors = utils.get_colors(len(mapper_series))
    colors_fig1 = {serie: dict_colors[i] for i, serie in enumerate(list(mapper_series.keys())[::-1], start=1)}

    # Convenient hours table for the graph
    hours = [f'{i:02}:00' for i in range(24)]
    df_shell = pd.DataFrame(hours, columns=['created_time'])

    # Invertimos el orden de las llaves, para que siempre aparezca en el orden correcto
    ordered_keys = list(mapper_series.keys())[::-1]

    for serie in ordered_keys:
        # Number of days to divide by and series' code
        days = re.findall(r'\d+', serie)
        serie_code = mapper_series[serie]

        # Filter the dataframe by the selected serie and group by created_time
        df_local = df_periodos[df_periodos[f'serie_{serie_code}'] == 1].copy(deep=True)
        df_grouped = df_local.groupby('created_time').agg({'user_id': 'count'})
        df_grouped.rename(columns={'user_id': 'subscribers'}, inplace=True)

        if serie == 'Today':
            # Extract hour component of time string and store it in shell_times list
            shell_times = [time for time in df_shell['created_time']
                           if int(re.findall(r'\d+', time)[0]) <= last_update.hour]
            
            # Truncate the shell dataframe to the current hour and merge it with the grouped dataframe
            df_shell_truncated = df_shell[df_shell['created_time'].isin(shell_times)].copy(deep=True)
            df_merged = pd.merge(df_shell_truncated, df_grouped, how='left', on='created_time')

        else: # Merge the shell with the dataframe
            df_merged = pd.merge(df_shell, df_grouped, how='left', on='created_time')
        
        df_merged['subscribers'] = df_merged['subscribers'].fillna(0)

        if serie not in ['Today', 'Yesterday']:
            df_merged['subscribers'] = df_merged['subscribers'] / int(days[0])  

        # Order by created_time and aggregate continuous values
        df_graph = df_merged.sort_values(by='created_time', ascending=True,
                                        ignore_index=True).copy(deep=True)
        
        df_graph[f'cum_{serie_code}'] = df_graph['subscribers'].cumsum()
        # df_graph.reset_index(drop=True, inplace=True)

        # Add linechart using plotly with the data of today by hour, on hover show the date and the value with only one decimal
        fig1.add_trace(go.Scatter(x=df_graph['created_time'], y=df_graph[f'cum_{serie_code}'],
                                mode='lines+markers', name=serie,
                                line=dict(color=colors_fig1[serie], width=2), 
                                hovertemplate=('<b>Hora:</b> %{x}<br>' + f'<b>{serie}</b>: ' + '%{y:.1f}<extra></extra>')))
    
    return fig1


### CREAMOS EL SEGUNDO GRÁFICO
# @st.cache_data
def prepare_fig02():
    # Add a pie chart with the percentage of each package for all active subscribers
    # df_local = df_graphs[df_graphs['created'].dt.date == last_update.date()].copy(deep=True)
    df_pi2 = df_graphs[df_graphs['created'].dt.date == last_update.date()].copy(deep=True)
    df_pie = df_graphs.groupby('packageName').agg({'created': 'count'}).reset_index(drop=False)

    # Do only consider the values in the dataframe, not the ones in the category table
    df_pie.drop(df_pie[df_pie['created'] == 0].index, inplace=True)

    # Rename the columns and sort the values
    df_pie.rename(columns={'created': 'count'}, inplace=True)

    # Define a sorting key function
    def sorting_key(name):
        # Create a dictionary to map each name to its position in the ordered list
        order_dict = {name: index for index, name in enumerate(ordered_plans[countries[0]])}

        # Return a tuple: (order position, name)
        # Names not in order_dict will get a large default order position
        return (order_dict.get(name, float('inf')), name)

    # Sort the names_to_order list using the custom sorting key
    unsorted_packages = df_pie['packageName'].to_list() if len(df_pie) > 1 else list(df_pie['packageName'].unique())

    if len(unsorted_packages) > 1:
        sorted_names = sorted(unsorted_packages, key=sorting_key)
    else:
        sorted_names = unsorted_packages

    # Create a custom categorical type with the specified order and use it to sort the DataFrame
    df_pie['packageName'] = pd.Categorical(df_pie['packageName'], categories=sorted_names, ordered=True)
    df_pie = df_pie.sort_values(by='packageName').reset_index(drop=True)

    # Define graph colors using the pinkly colors
    dict_colors = utils.get_colors(len(df_pie))
    colors_fig2 = [dict_colors[i+1] for i in range(len(df_pie))][::-1]

    fig2 = go.Figure()
    fig2.add_trace(go.Pie(labels=df_pie['packageName'], values=df_pie['count'],
                        hole=0.3, sort=False, marker=dict(colors=colors_fig2)))

    # Show the total sum of the pie chart inside the hole
    fig2.update_traces(textinfo='percent+label', textfont_size=14,
                    textposition='outside')#, rotation=90)

    # Show the total sum of the pie chart inside the hole
    total = df_graphs['user_id'].count()
    # df_pi2[(df_pi2['planStatus'].isin(plan_status))]['user_id'].count()

    # Update the layout of the graph with automated font size
    fig2.update_layout(#title='Porcentaje de suscripciones por plan', 
        showlegend=False, annotations=[
        dict(text=f'Total<br>{total:0.0f}', x=0.5, y=0.5, showarrow=False)])
    
    return fig2, df_pie, colors_fig2


### CREAMOS EL TERCER GRÁFICO
# @st.cache_data
def prepare_fig03():
    # Colors per package from the pie chart
    colors_fig3 = {df_pie['packageName'][i]: colors_fig2[i] for i in range(len(df_pie))}

    # Add a plotly graph
    fig3 = go.Figure()

    # Group by created_date and sum the serie for each day
    df_fig3 = df_graphs.copy(deep=True)
    df_fig3['created_date'] = df_fig3['created'].dt.date
    df_grouped = df_fig3.groupby(['created_date', 'packageName'])\
        .agg({'user_id': 'count'}).reset_index()

    # Order by fig2 to remain consistent
    df_grouped = pd.merge(df_pie, df_grouped, how='left', on='packageName')
    # df_grouped.sort_values(by='count', ascending=True, ignore_index=True, inplace=True)

    # Define a sorting key function
    def sorting_key(name):
        # Create a dictionary to map each name to its position in the ordered list
        order_dict = {name: index for index, name in enumerate(ordered_plans[countries[0]])}

        # Return a tuple: (order position, name)
        # Names not in order_dict will get a large default order position
        return (order_dict.get(name, float('inf')), name)

    # Sort the names_to_order list using the custom sorting key
    # Sort the names_to_order list using the custom sorting key
    unsorted_packages = df_pie['packageName'].to_list() if len(df_pie) > 1 else list(df_pie['packageName'].unique())
    
    if len(unsorted_packages) > 1:
        sorted_names = sorted(unsorted_packages, key=sorting_key, reverse=True)
    else:
        sorted_names = unsorted_packages

    # # Define graph colors using the pinkly colors
    # unsorted_packages = df_grouped['packageName'].unique()
    # sorted_names = sorted(unsorted_packages, key=sorting_key, reverse=True)

    # Order the dataframe by the sorted names
    df_grouped['packageName'] = pd.Categorical(df_grouped['packageName'], categories=sorted_names, ordered=True)
    df_grouped = df_grouped.sort_values(by='packageName').reset_index(drop=True)

    dict_colors = utils.get_colors(len(sorted_names))
    colors_graph02 = {package: dict_colors[i]
                      for i, package in enumerate(sorted_names, start=1)}

    # Add an invisible trace for the total of suscriptions, and use it to be shown on hover
    df_grouped['total'] = df_grouped.groupby('created_date')['user_id'].transform('sum')
    fig3.add_trace(go.Scatter(x=df_grouped['created_date'], y=df_grouped['total'], 
                        marker=dict(color='rgba(0,0,0,0)'),  # make bar invisible
                        hovertemplate='<b>Total:   %{y}<extra></extra></b>',  # customize hover text
                        hoverinfo='y',  # only show y value in hover
                        showlegend=False))  # hide legend entry

    # Create a graph for each package and add it to the figure
    for package in df_grouped['packageName'].unique():
        df_local = df_grouped[df_grouped['packageName'] == package].copy(deep=True)
        df_local.sort_values(by='created_date', ascending=True, ignore_index=True, inplace=True)
        fig3.add_trace(go.Bar(x=df_local['created_date'], y=df_local['user_id'], name=package,
                            marker=dict(color=colors_graph02[package])))

    # Update the layout of the graph and zoom on the values for the last 30 days by default
    last_30_days = last_update.date() - timedelta(days=30)

    # Define max y value for the graph
    max_y = max(df_grouped[df_grouped['created_date'] >= last_30_days]['total']) * 1.1

    fig3.update_layout(barmode='stack', #title='Suscripciones por día y plan', 
                    xaxis_title='Fecha', xaxis=dict(range=[last_30_days, last_update.date()]),
                    yaxis_title='Suscriptores', yaxis=dict(range=[0, max_y]),
                    legend_title='Planes', hovermode='x unified')
    
    return fig3


### CREAMOS EL CUARTO GRAFICO
# @st.cache_data
def prepare_fig04():
    fig4 = go.Figure()

    df_churn = df_graphs.copy(deep=True)
    df_churn['chargebee_cancel_scheduled_at'] = df_churn['chargebee_cancel_scheduled_at'].dt.date
    df_churn['chargebee_cancelled_at'] = df_churn['chargebee_cancelled_at'].dt.date

    mapper_methods = {'Cancel Scheduled': 'chargebee_cancel_scheduled_at', 'Cancelled': 'chargebee_cancelled_at'}
    colors_fig4 = utils.get_colors(len(mapper_methods.keys()))
    max_bar = []

    for i, method in enumerate(methods, start=1):
        df_local = df_churn.groupby(mapper_methods[method])\
            .agg({'user_id': 'count'}).reset_index()
        
        max_bar.append(df_local['user_id'].max())

        # Add a linechart using plotly with the data of today by hour, on hover show the date and the value with only one decimal
        fig4.add_trace(go.Bar(x=df_local[mapper_methods[method]], y=df_local['user_id'], hoverinfo='y',  # only show y value in hover
                            hovertemplate=f'<b>{method}:</b>' + ' %{y}<extra></extra>',  # customize hover text
                            marker=dict(color=colors_fig4[i]),
                            showlegend=False))
        
    # Update the layout of the graph and zoom on the values for the last 30 days by default
    last_30_days = last_update.date() - timedelta(days=30)

    # Define max y value for the graph
    max_y = max(max_bar) * 1.1

    fig4.update_layout(title='Churn por día',
                    xaxis_title='Fecha', xaxis=dict(range=[last_30_days, last_update.date()]),
                    yaxis_title='Churn', yaxis=dict(range=[0, max_y]), hovermode='x unified')

    return fig4

### CREAMOS EL QUINTO GRAFICO

# email = st.text_input('Customer ID')

# # Filter the dataframe by the selected countries
# df_retention = df_graphs[(df_graphs['countryName'].isin(countries)) &
#                        (df_graphs['isB2B'].isin([mapper_b2b[elem] for elem in is_b2b])) &
#                        (df_graphs['main'].isin([plan_type_mapper[plan]
#                                               for plan in plan_type]))].copy(deep=True)

# # st.write(df_retention[df_retention['email']==email])

# # Retention dataframe based on the base dataframe, with the lifetime added
# # df_retention = df_retention[['created', 'updated', 'planStatus']].copy(deep=True)
# df_retention.dropna(subset=['updated'], inplace=True)


# df_retention['deactivated'] = df_retention[df_retention['planStatus']=='inactive']['updated']
# df_retention['lifetime'] = (df_retention['updated'] - df_retention['created']).dt.days

# # Slider to select the number of months to check for
# x_months = st.slider('XMRR', 3, 12, 0)

# Summate one month to the created column, generating a new column with the date of the retention
# df_retention['x_months'] = df_retention['created'] + pd.DateOffset(months=x_months)
# df_retention['slider_stop'] = df_retention['created'] + pd.DateOffset(months=retention+1)\
#       - pd.DateOffset(days=1)

# Now we calculate if the deactivated date is between the slider_start and slider_stop
# df_retention['retention'] = df_retention.apply(lambda x: 1 if x['deactivated'] >= x['slider_start'] \
#                                                and x['deactivated'] <= x['slider_stop'] else 0, axis=1)

# # Get retention independent of the exact number of months
# df_retention.loc[df_retention['deactivated']<=df_retention['x_months'], 'churn'] = 1
# df_retention.loc[df_retention['churn'].isnull(), 'retention'] = 1

# # Retention rate for each date
# df_retention['created_dt'] = df_retention['created'].dt.date
# df_grouped = df_retention.groupby('created_dt').agg({'churn': 'sum',
#                                                      'retention': 'sum',
#                                                      'created': 'count'}).reset_index()

# df_grouped['total'] = df_grouped['churn'] + df_grouped['retention']
# df_grouped.sort_values(by='created_dt', ascending=False,
#                        ignore_index=True, inplace=True)

# # Filtering by the slider value
# df_retention = df_retention[df_retention['created'].between(santiago_now, )].copy(deep=True)
# df_retention = df_retention[df_retention['lifetime'] <= retention * 30].copy(deep=True)
# yesterday = df_retention['created_dt'].max()
# st.write(df_retention[df_retention['created_dt']==yesterday]) #df_retention[df_retention['churn']==1])
# st.write(df_grouped)


# Create plotly graph showing the retention rate for each date


# Custom function to create a nice box for displaying numbers
def create_number_box(label, number, color):
    html_string = f"""
    <div style='background-color: {color};  padding: 10px; border-radius: 10px'>
        <h1 style='color: white; text-align: center;'>{number}</h1>
        <p style='color: white; text-align: center;'>{label}</p>
    </div>
    """
    return html_string

def add_blankspace(units):
    html_string = '<style>.spacer {height: ' + units + ';}</style><div class="spacer"></div>'
    return html_string

#########
# @st.cache_data
def prepare_fig05(df_xmrr):
    df_xmrr = df_xmrr[(df_xmrr['countryName'].isin(countries)) &
                    (df_xmrr['isB2B'].isin([mapper_b2b[elem] for elem in is_b2b])) &
                    (df_xmrr['main'].isin([plan_type_mapper[plan] for plan in plan_type])) &
                    (df_xmrr['created'].dt.date <= last_update.date()) &
                    (df_xmrr['coupon_name'].isin(coupons))].copy(deep=True) #&
                    #   (df_xmrr['packageID']>70)]

    # Creation of created_date and updated_date columns
    df_xmrr['created_date'] = df_xmrr['created'].dt.date
    df_xmrr['updated_date'] = df_xmrr['updated'].dt.date

    # If the user is inactive, we calculate the number of days between updated and created,
    # otherwise we calculate the number of days between today and created
    df_xmrr['days_since_creation'] = df_xmrr.apply(lambda x: (x['updated_date'] - x['created_date']).days
                                                    if x['planStatus'] == 'inactive'
                                                    else (last_update.date() - x['created_date']).days, axis=1)

    # Reduction of the dataframe to the columns of interest
    df_xmrr = df_xmrr[['user_id', 'created_date', 'updated', 'planStatus',
                    'days_since_creation']].copy(deep=True)

    # If days_since_creation is less than months_subscribed * 30, we set a true value for the active_after_x column
    df_xmrr['active_after_x'] = df_xmrr.apply(lambda x: 1 if x['days_since_creation'] >= (months_subscribed * 30)
                                            else 0, axis=1)

    # Group by created_date and calculate the XMRR
    df_grouped_xmrr = df_xmrr.groupby('created_date').agg({'user_id': 'count',
                                                        'active_after_x': 'sum'}).reset_index()

    df_grouped_xmrr['xmrr'] = df_grouped_xmrr['active_after_x'] / df_grouped_xmrr['user_id']

    # Create a plotly graph showing the XMRR for each date
    fig5 = go.Figure()

    # Show on hover the value as a percentage number with two decimals
    fig5.add_trace(go.Scatter(x=df_grouped_xmrr['created_date'], y=df_grouped_xmrr['xmrr'],
                            mode='lines+markers', name=None,
                            line=dict(color='#f63366', width=2), # On hover show user_id count and the value with two decimals
                            hovertemplate=('<extra></extra><b>Total subscribers:</b> %{text}<br>' + 
                                            '<b>XMRR:</b> %{y:.2%}'),
                                            text=df_grouped_xmrr['user_id']))  # Passing user_id count for hover info
        
    # First day of the current year and last day by default
    first_date = datetime(last_update.year, 1, 1)
    last_x_days = last_update - timedelta(days=months_subscribed * 30)


    # Update the layout of the graph and zoom on the values for the last 30 days by default
    fig5.update_layout(title='XMRR por día', xaxis_title='Fecha', xaxis=dict(range=[first_date, last_x_days]),
                    yaxis_title='XMRR', hovermode='x unified')
    
    return fig5, df_grouped_xmrr


# FLOW GRAPHS TABLE LOADER

def bigquery_analytics_data():
    # Levantando las credenciales de BigQuery y creando el cliente
    bigquery_json = credentials.get_json('zapping-datalake')
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = bigquery_json
    clients = {'bigquery': bigquery.Client()}

    # Definiendo los argumentos para la función
    args = {'project': 'zapping-datalake', 'dataset': 'growth',
            'table': 'funnel_analytics'}
    
    # Función para obtener los datos de BigQuery
    query_gbq = """ SELECT
                        *
                    FROM
                        `{project}.{dataset}.{table}`
                """.format(**args)
    
    @st.cache_data
    def load_bigquery():
        df_flow = clients['bigquery'].query(query_gbq).to_dataframe(
            progress_bar_type=tqdm)
        
        return df_flow
    
    # Load the dataframe
    df_flow = load_bigquery()

    # Preparing countries filter to be applied to the dataframe
    mapper_countries = {'Chile': 'Chile', 'Brasil': 'Brasil',
                        'Peru': 'Perú', 'Ecuador': 'Ecuador'}
    
    mapped_countries = [mapper_countries[country] for country in countries]

    # Filter the dataframe by the selected countries and transform the date column to datetime
    df_flow = df_flow[df_flow['country'].isin(mapped_countries)].copy(deep=True)
    df_flow['dttm'] = pd.to_datetime(df_flow['dt'])

    # Adding aditional columns for the week and year
    df_flow['day'] = df_flow['dttm'].dt.date
    df_flow['week'] = df_flow['dttm'].dt.isocalendar().week
    df_flow['month'] = df_flow['dttm'].dt.month
    df_flow['year'] = df_flow['dttm'].dt.isocalendar().year
    
    # Establecer la columna de fecha como índice
    df_flow.set_index('dttm', inplace=True)

    # Define the aggregation dictionary and the frequency of the aggregation
    mapper_aggregation = {'Días': 'D', 'Semanas': 'W', 'Meses': 'M', 'Años': 'Y'}
    freq_aggregation = mapper_aggregation[date_aggregation]

    # Define the columns to aggregate
    mapper_dates = {'Días': ['day'], 'Semanas': ['year', 'week'], 'Meses': ['year', 'month'], 'Años': ['year']}
    date_cols = mapper_dates[date_aggregation]

    return df_flow, freq_aggregation, date_cols


# CREAMOS EL SEXTO GRÁFICO
def prepare_fig06(df_flow, freq_aggregation, date_cols):
    df_flow_filtered = df_flow.copy(deep=True)

    # Group and avoid showing the index
    mapper_cols = {'kpi_02A_register_plan': r'% Seleccionan Plan',
                   'kpi_02B_register_payment': r'% Pasan al Pago',
                   'kpi_02C_register_confirmation': r'% Confirman su Plan',
                   'kpi_02D_register_success': r'% Suscriben'}
    
    df_flow_filtered.rename(columns=mapper_cols, inplace=True)

    # Define the aggregation dictionary
    dict_agg = {**{col: 'max' for col in date_cols},
                # **{'landing': 'sum', 
                **{'register': 'sum', '% Seleccionan Plan': 'mean',
                '% Pasan al Pago': 'mean', '% Confirman su Plan': 'mean', '% Suscriben': 'mean'}}

    df_flow_filtered = df_flow_filtered.groupby(pd.Grouper(freq=freq_aggregation)).agg(
        dict_agg).sort_values(by=date_cols, ascending=False).copy(deep=True)

    # Función para formatear números con puntos como separadores de miles y comas como separadores decimales
    def format_number(x):
        return '{:,.0f}'.format(x).replace(',', 'X').replace('.', ',').replace('X', '.')

    def format_percent(x):
        return '{:.2%}'.format(x).replace('.', ',')

    # Define el formato para las columnas usando style.format y las funciones personalizadas
    df_style = df_flow_filtered.style.format({
        # 'landing': format_number,
        'register': format_number,
        '% Seleccionan Plan': format_percent,
        '% Pasan al Pago': format_percent,
        '% Confirman su Plan': format_percent,
        '% Suscriben': format_percent
    })

    st.dataframe(df_style, hide_index=True, use_container_width=True)#, height=280)


# CREAMOS EL SÉPTIMO GRÁFICO
    
def prepare_fig07(df_flow, freq_aggregation, date_cols, max_bars):
    cols = ['landing', 'register', 'plan', 'payment', 'confirmation', 'success']
    df_flow_filtered = df_flow[date_cols + cols].sort_values(by=date_cols + cols,
                                                             ascending=False).copy(deep=True)
    if len(date_cols) > 1:
        df_flow_filtered['date_key'] = df_flow_filtered[date_cols].apply(
            lambda x: '-'.join(x.astype(str).str.zfill(2)), axis=1)
    else:
        df_flow_filtered['date_key'] = df_flow_filtered[date_cols].astype(str)

    # Define the aggregation dictionary
    dict_agg = {**{'date_key': 'max'}, **{col: 'sum' for col in cols}}

    # Group, drop unnecessary columns and the index
    df_flow_grouped = df_flow_filtered.groupby(pd.Grouper(freq=freq_aggregation)).agg(
        dict_agg).sort_values(by='date_key', ascending=True).reset_index(drop=True).copy(deep=True)
    
    # Create a plotly graph showing the flow for each date for each column in cols as a bar chart
    fig7 = go.Figure()

    # Define the colors for the graph 
    dict_colors = utils.get_colors(len(cols))

    # Adding each group
    for i, col in enumerate(cols, start=1):
        fig7.add_trace(go.Bar(x=df_flow_grouped['date_key'], y=df_flow_grouped[col],
                              name=col, marker=dict(color=dict_colors[i])))
        
    # make sure the x-axis uses 'date_key'
    fig7.update_xaxes(type='category')

    # Define end_index as the last index in the dataframe, and the start index 10 indexes before the end
    end_index = len(df_flow_grouped) - 0.5

    if end_index < max_bars:
        start_index = -0.5
    else:
        start_index = end_index - max_bars

    # Update the layout of the graph and zoom on the values for the last 7 dates, and add a margin to the x axis
    mapper_freq = {'D': 'Días', 'W': 'Semanas', 'M': 'Meses', 'Y': 'Años'}
    fig7.update_layout(title='Flujo del Registro', xaxis_title=f'Fecha agregada por {mapper_freq[freq_aggregation]}',
                    yaxis_title='Prospectos', hovermode='x unified', 
                    xaxis=dict(
                           range=[start_index, end_index],
                           tickvals=list(range(len(df_flow_grouped.index))),
                           ticktext=df_flow_grouped.index))
    
    # Update the tickers to show the date_key
    fig7.update_xaxes(tickvals=list(range(len(df_flow_grouped.index))),
                    ticktext=df_flow_grouped['date_key'])
    
    st.plotly_chart(fig7, use_container_width=True)


# CREAMOS EL OCTAVO GRÁFICO

def prepare_fig08(df_flow, freq_aggregation, date_cols):
    df_flow_filtered = df_flow.copy(deep=True)

    # Group and avoid showing the index
    mapper_cols = {'register_time': r'T° Registro', 'plan_time': r'T° Selección del Plan',
                   'payment_time': r'T° Medios de Pago', 'confirmation_time': r'T° Confirmación',
                   'success_time': r'T° Success', 'time_from_register': r'T° Total'}
    
    df_flow_filtered.rename(columns=mapper_cols, inplace=True)

    # Define the aggregation dictionary
    dict_agg = {**{col: 'max' for col in date_cols},
                # **{'landing': 'sum', 'register': 'sum', 
                   **{'T° Registro': 'mean',
                'T° Selección del Plan': 'mean', 'T° Medios de Pago': 'mean',
                'T° Confirmación': 'mean', 'T° Success': 'mean',
                'T° Total': 'mean'}}

    df_flow_filtered = df_flow_filtered.groupby(pd.Grouper(freq=freq_aggregation)).agg(
        dict_agg).sort_values(by=date_cols, ascending=False).copy(deep=True)

    # # Función para formatear números con puntos como separadores de miles y comas como separadores decimales
    # def format_number(x):
    #     return '{:,.0f}'.format(x).replace(',', 'X').replace('.', ',').replace('X', '.')

    # Función para formatear tiempos en el formato "x min y seg"
    def format_time(x):
        minutes = int(x // 60)
        seconds = int(x % 60)
        return f"{minutes} min {seconds} seg"

    # Define el formato para las columnas usando style.format y las funciones personalizadas
    df_style = df_flow_filtered.style.format({
        # 'landing': format_number,
        # 'register': format_number,
        'T° Registro': format_time,
        'T° Selección del Plan': format_time,
        'T° Medios de Pago': format_time,
        'T° Confirmación': format_time,
        'T° Success': format_time,
        'T° Total': format_time
    })

    st.dataframe(df_style, hide_index=True, use_container_width=True)#, height=280)


# CREAMOS EL NOVENO GRÁFICO
    
def prepare_fig09(df_flow, freq_aggregation, date_cols, max_bars):
    cols = ['time_from_register', 'success_time', 'confirmation_time',
            'payment_time', 'plan_time', 'register_time']
    
    df_flow_filtered = df_flow[date_cols + cols].sort_values(by=date_cols + cols,
                                                             ascending=False).copy(deep=True)
    if len(date_cols) > 1:
        df_flow_filtered['date_key'] = df_flow_filtered[date_cols].apply(
            lambda x: '-'.join(x.astype(str).str.zfill(2)), axis=1)
    else:
        df_flow_filtered['date_key'] = df_flow_filtered[date_cols].astype(str)

    # Define the aggregation dictionary
    dict_agg = {**{'date_key': 'max'}, **{col: 'mean' for col in cols}}

    # Group, drop unnecessary columns and the index
    df_flow_grouped = df_flow_filtered.groupby(pd.Grouper(freq=freq_aggregation)).agg(
        dict_agg).sort_values(by='date_key', ascending=True).reset_index(drop=True).copy(deep=True)
    
    # Create a plotly graph showing the flow for each date for each column in cols as a stacked bar chart
    fig09 = go.Figure()

    # Define the colors for the graph 
    dict_colors = utils.get_colors(len(cols)-1)

    # Reversing the colors for the graph
    dict_keys = list(dict_colors.keys())
    reversed_colors = {key: dict_colors[dict_keys[-key]] for key in dict_colors.keys()}

    # Adding each group
    for i, col in enumerate(cols):
        if col == 'time_from_register':
            fig09.add_trace(go.Scatter(
                x=df_flow_grouped['date_key'], y=df_flow_grouped[col],
                name=col, marker=dict(color='rgba(0, 0, 0, 0)'),
                showlegend=False
            ))
        else:
            fig09.add_trace(go.Bar(
                x=df_flow_grouped['date_key'], y=df_flow_grouped[col],
                name=col, marker=dict(color=reversed_colors[i])
            ))
        
    # make sure the x-axis uses 'date_key'
    fig09.update_xaxes(type='category')

    # Define end_index as the last index in the dataframe, and the start index 10 indexes before the end
    end_index = len(df_flow_grouped) - 0.5

    if end_index < max_bars:
        start_index = -0.5
    else:
        start_index = end_index - max_bars

    # Update the layout of the graph and zoom on the values for the last 7 dates, and add a margin to the x axis
    mapper_freq = {'D': 'Días', 'W': 'Semanas', 'M': 'Meses', 'Y': 'Años'}
    fig09.update_layout(
        title='Tiempo de Registro', 
        xaxis_title=f'Fecha agregada por {mapper_freq[freq_aggregation]}', 
        yaxis_title='Segundos', 
        hovermode='x unified', 
        xaxis=dict(
            range=[start_index, end_index],
            tickvals=list(range(len(df_flow_grouped.index))),
            ticktext=df_flow_grouped.index
        ),
        barmode='stack'
    )
    
    # Update the tickers to show the date_key
    fig09.update_xaxes(
        tickvals=list(range(len(df_flow_grouped.index))),
        ticktext=df_flow_grouped['date_key']
    )
    
    # Custom hover template to show "x min y seg"
    def custom_hover_template(seconds):
        minutes = int(seconds // 60)
        remaining_seconds = int(seconds % 60)
        return f"{minutes} min {remaining_seconds} seg"

    # Updating the hovertemplate for each trace
    for trace in fig09.data:
        if trace.name == 'time_from_register':
            trace.hovertemplate = (
                '<b>Total</b>: %{customdata}<br>'
                '<extra></extra>'
            )
        else:
            trace.hovertemplate = (
                '<b>Serie</b>: ' + trace.name + '<br>'
                '<b>Tiempo</b>: %{customdata}<br>'
                '<extra></extra>'
            )
        # Attach customdata for hovertemplate
        trace.customdata = [custom_hover_template(y) for y in trace.y]

    st.plotly_chart(fig09, use_container_width=True)


# CREAMOS EL DECIMO GRAFICO

def prepare_fig10(df_flow, freq_aggregation, date_cols):
    def bigquery_analytics_data():
        # Levantando las credenciales de BigQuery y creando el cliente
        bigquery_json = credentials.get_json('zapping-datalake')
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = bigquery_json
        clients = {'bigquery': bigquery.Client()}

        # Definiendo los argumentos para la función
        args = {'project': 'zapping-datalake', 'dataset': 'growth',
                'table': 'funnel_analytics'}

        # Función para obtener los datos de BigQuery
        query_gbq = """ SELECT
                            *
                        FROM
                            `{project}.{dataset}.{table}`
                    """.format(**args)

        @st.cache_data
        def load_bigquery():
            df_flow = clients['bigquery'].query(query_gbq).to_dataframe(
                progress_bar_type=tqdm)
            
            return df_flow

    # Crear un gráfico de barras con los usuarios únicos por user_creation in absolute values
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df_merged['user_creation'].dt.date.value_counts().index,
                        y=df_merged['user_creation'].dt.date.value_counts().values,
                        name='Unique Users', marker_color='green'))
    fig.update_layout(title='Unique Users by User Creation Date',
                        xaxis_title='User Creation Date',
                        yaxis_title='Unique Users')
    fig.show()


# DESPLEGAMOS LOS GRÁFICOS
if page == 'Adquisición':
    # Prepare the main dataframe
    df_graphs, df_xmrr, last_update = prepare_main()

    # Define the columns to display the graphs in two columns of dimension 1:4
    col1, col2 = st.columns([1, 4])

    # Prepare the figures
    fig01 = prepare_fig01()
    fig02, df_pie, colors_fig2 = prepare_fig02()
    fig03 = prepare_fig03()

    with col1:
        unique_users = df_graphs['user_id'].nunique()
        new_users  = df_graphs[df_graphs['created'].dt.date == df_graphs['created'].max().date()]['user_id'].nunique()

        # Add vertical space using CSS
        st.markdown(add_blankspace('10rem'), unsafe_allow_html=True)
        st.markdown(create_number_box('Usuarios Únicos', unique_users, "#f63366"), unsafe_allow_html=True)
        st.markdown(add_blankspace('3rem'), unsafe_allow_html=True)
        st.markdown(create_number_box('Nuevos Usuarios', new_users, "#f63366"), unsafe_allow_html=True)
        # st.markdown(add_blankspace('5px'), unsafe_allow_html=True)
        # st.markdown(create_number_box('Usuarios Únicos', unique_users, "#f63366"), unsafe_allow_html=True)

    with col2:
        st.plotly_chart(fig01, use_container_width=True)

        # df_download = df_graphs[df_graphs['created'].dt.date==datetime.now().date()].copy(deep=True)
        # st.write(df_download)

        # #Make all timezone aware columns timezone naive
        # cols_timezone = ['created', 'updated', 'extraction_dttm', 'coupon_used', 'coupon_created',
        #                  'mysql_cancel_scheduled_at', 'mysql_cancelled_at', 'chargebee_cancel_scheduled_at',
        #                  'chargebee_cancelled_at']
        
        # for col in cols_timezone:
        #     df_download[col] = df_download[col].dt.tz_localize(None)
        
        # df_download.to_excel('date_graphs.xlsx', index=False)

    # Define the columns to display the graphs in two columns of dimension 2:1
    col3, col4 = st.columns([3, 2])

    with col3:
        st.plotly_chart(fig03, use_container_width=True)

    with col4:
        # Adapt figure size to the container width, considering the legend
        fig02.update_layout(autosize=True, width=380, height=380, 
                            legend=dict(orientation='h', yanchor='bottom',
                                        y=1.02, xanchor='left', x=1))

        st.plotly_chart(fig02, use_container_width=True)

if page == 'Churn':
    # Prepare the main dataframe
    df_graphs, df_xmrr, last_update = prepare_main()

    # Define the columns to display the graphs in two columns of dimension 1:4
    # col1, col2 = st.columns([1, 4])

    # Prepare the figures
    fig04 = prepare_fig04()
    fig05, df_grouped_xmrr = prepare_fig05(df_xmrr)

    st.plotly_chart(fig04, use_container_width=True)

    st.plotly_chart(fig05, use_container_width=True)

    st.write(df_grouped_xmrr[df_grouped_xmrr['created_date']>datetime.strptime('2021-06-01', '%Y-%m-%d').date()]['xmrr'].mean())

    # st.download_button("Download file", df_grouped.to_csv(), "data.csv", "text/csv")
    # st.write(df_xmrr)

# CREAMOS EL GRÁFICO DE PRUEBAS
def prepare_test(df_flow, freq_aggregation, date_cols):
    df_flow_filtered = df_flow.copy(deep=True)

    # Group and avoid showing the index
    mapper_cols = {'plan': r'Seleccionan Plan',
                   'payment': r'Pasan al Pago',
                   'confirmation': r'Confirman su Plan',
                   'success': r'Suscriben'}
    
    df_flow_filtered.rename(columns=mapper_cols, inplace=True)

    # Define the aggregation dictionary
    dict_agg = {**{col: 'max' for col in date_cols},
                # **{'landing': 'sum', 
                **{'register': 'sum', 'Seleccionan Plan': 'sum',
                'Pasan al Pago': 'sum', 'Confirman su Plan': 'sum', 'Suscriben': 'sum'}}

    df_flow_filtered = df_flow_filtered.groupby(pd.Grouper(freq=freq_aggregation)).agg(
        dict_agg).sort_values(by=date_cols, ascending=False).copy(deep=True)

    # Función para formatear números con puntos como separadores de miles y comas como separadores decimales
    def format_number(x):
        return '{:,.0f}'.format(x).replace(',', 'X').replace('.', ',').replace('X', '.')

    def format_percent(x):
        return '{:.2%}'.format(x).replace('.', ',')

    # Define el formato para las columnas usando style.format y las funciones personalizadas
    df_style = df_flow_filtered.style.format({
        # 'landing': format_number,
        'register': format_number,
        'plan': format_number,
        'payment': format_number,
        'confirmation': format_number,
        'success': format_number
    })

    return df_style#, height=280)

if page == 'Flujo':
   # Define the columns to display the graphs in two columns of dimension 1:4
    df_flow, freq_aggregation, date_cols = bigquery_analytics_data()

    # Crear las columnas con espacios específicos para la línea divisoria
    row1_col1, row1_col2, row1_col3 = st.columns([4, 0.5, 4])

    with row1_col1:
        prepare_fig07(df_flow, freq_aggregation, date_cols, max_bars)

    with row1_col3:
        prepare_fig09(df_flow, freq_aggregation, date_cols, max_bars)
        

    # Segunda fila
    row2_col1, row2_col2, row2_col3 = st.columns([4, 0.5, 4])

    with row2_col1:
        prepare_fig06(df_flow, freq_aggregation, date_cols)

    with row2_col3:
        prepare_fig08(df_flow, freq_aggregation, date_cols)

    df_test = prepare_test(df_flow, freq_aggregation, date_cols)
    st.dataframe(df_test, hide_index=True, use_container_width=True)

if page == 'Eventos':
    import time
    import re
    # event_start_date, event_start_time, event_end_date, event_end_time, 
    # event_channel, event_country, button_update
    event_start_str = event_start_date.strftime('%Y-%m-%d') + ' ' + event_start_time.strftime('%H:%M')
    event_end_str = event_end_date.strftime('%Y-%m-%d') + ' ' + event_end_time.strftime('%H:%M')

    # Read the code from the file
    if button_update: # If the button is pressed
        with open('etl_attribution_events.py', 'r+') as file:
            code = file.read()

            # Replace values from the code and store it on the file
            code = re.sub(r'event_start = .* # Formato:', f"event_start = '{event_start_str}' # Formato:", code)
            code = re.sub(r'event_end = .* # Formato:', f"event_end = '{event_end_str}' # Formato:", code)
            code = re.sub(r'channel = .* # Canal', f"channel = '{event_channel}' # Canal", code)
            code = re.sub(r'country = .* # País', f"country = '{event_country}' # País", code)
            code = re.sub(r'tiempo = .* # Tiempo', f"tiempo = {time_connected} * 60 # Tiempo", code)

            # Volvemos el cursor al principio del archivo, borramos su contenido y escribimos el nuevo código
            file.truncate()
            file.seek(0)
            file.write(code)

            # Execute the code using subprocess
            subprocess.run(['python', 'etl_attribution_events.py'])

        path_dashboard = utils.script_path([origin, folder, 'storage', 'df_events_funnel.pkl'])
        df_events = pd.read_pickle(path_dashboard)
        st.dataframe(df_events.sort_values(by='user_creation', ascending=False))

        st.write(len(df_events['user_id'].unique()))
        st.write(df_events['duration'].mean()/60)

        # Crear un gráfico de barras con los usuarios únicos por user_creation in absolute values
        fig = go.Figure()

        # Contar los valores de las fechas de creación de usuarios y ordenarlos por fecha
        date_counts = df_events['user_creation'].dt.date.value_counts().sort_index()

        fig.add_trace(go.Bar(x=date_counts.index,
                            y=date_counts.values,
                            name='Unique Users', marker_color='green'))

        # Acotar el rango de fechas a 3 días antes del event_announcement y el alto al segundo mayor valor
        second_largest = date_counts.nlargest(2).values[1]
        lower_date = (event_announcement - timedelta(days=1))
        higher_date = (event_end_date + timedelta(days=1))

        fig.update_layout(
            title='Unique Users by User Creation Date',
            xaxis_title='User Creation Date',
            yaxis_title='Unique Users',
            barmode='group',
            bargap=0.2,  # Adjust gap between bars
            xaxis=dict(
                range=[lower_date, higher_date],
                tickmode='linear',  # Ensure linear ticks
                dtick="D1",  # One day interval
                nticks=len(date_counts) + 2,  # Number of ticks (including padding)
                tickformat='%Y-%m-%d',  # Format ticks as dates
                # tickangle=-30  # Optional: Rotate tick labels for better readability
            ),
            yaxis=dict(
                range=[0, second_largest * 1.1]
            )
        )

        # Mostrar el número de usuarios suscritos desde event_announcement hasta event_end_date
        df_subscribed = df_events[df_events['user_creation'].dt.date.between(event_announcement,
                                                                     event_end_date)].copy(deep=True)
        subscribed = df_subscribed['user_id'].nunique()

        # Mostrar número de usuarios activos al día de hoy
        active_users = df_events[(df_events['user_creation'].dt.date.between(event_announcement, event_end_date)) &
                                 (df_events['plan_status'] != 'inactive')]['user_id'].nunique()

        col1, col2 = st.columns([1, 1])

        with col1:
            st.plotly_chart(fig)

        with col2:
            st.markdown(add_blankspace('3rem'), unsafe_allow_html=True)
            st.markdown(create_number_box('Usuarios Suscritos', subscribed, "#f63366"), unsafe_allow_html=True)

            st.markdown(add_blankspace('3rem'), unsafe_allow_html=True)
            st.markdown(create_number_box('Usuarios Activos al día de hoy', active_users, "#f63366"), unsafe_allow_html=True)

        st.code(code, language='python')



    st.write('hello world')
    