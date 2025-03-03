# rsconnect deploy shiny ./ --name realdealfinder --title real-deal-finder

from pathlib import Path
from shiny import reactive
from shiny.express import input, render, ui
from shinywidgets import render_plotly
import plotly.express as px
import pandas as pd
import numpy as np
import os

ui.page_opts(fillable=True)

colorlist = px.colors.qualitative.Plotly.reverse()
# Read nowcast for visualization
rank_cols = ['BATHRM','HF_BATHRM','BEDRM','GBA','YR_RMDL','EYB']
nowcast_price_col = 'nowcast_prediction'
address_col = 'ADDRESS'
location_cols = ['LATITUDE','LONGITUDE']
nowcast_select_cols = [*rank_cols,nowcast_price_col,address_col,*location_cols]
preds_df = pd.read_csv('nowcast_predictions.csv',
                       usecols=nowcast_select_cols)
preds_df['YR_RMDL'] = preds_df['YR_RMDL'].fillna(0)
preds_df['HF_BATHRM'] = preds_df['HF_BATHRM'].fillna(0)
preds_df = preds_df.dropna()
preds_df = preds_df.rename({'ADDRESS':'Address'}, axis='columns')
address_col = 'Address'
preds_df = preds_df.rename({'nowcast_prediction':'Nowcast'}, axis='columns')
nowcast_price_col = 'Nowcast'
pretty_names = {
                'GBA':'Square Ft',
                'BEDRM':'Bedrooms',
                'BATHRM':'Bathrooms',
                'EYB':'Year Built/Remodeled',
            }
preds_df['HF_BATHRM'] = preds_df['HF_BATHRM'] / 2
preds_df['BATHRM'] = preds_df['BATHRM'] + preds_df['HF_BATHRM']
preds_df = preds_df.drop('HF_BATHRM', axis=1)
rank_cols.remove('HF_BATHRM')
preds_df['EYB'] = preds_df[['EYB','YR_RMDL']].max(axis=1)
preds_df = preds_df.drop('YR_RMDL', axis=1)
rank_cols.remove('YR_RMDL')

addresses = list(preds_df[address_col].sort_values())

ui.page_opts(title="Real Deal Finder", fillable=True)

@reactive.effect
def _():
    ui.update_selectize(
        id='selectize',
        choices=addresses,
        server=True
    )

@reactive.calc
def subset_nowcast():
    if not input.selectize():
        return pd.DataFrame()  # Return empty DataFrame if nothing selected
    selected_rows = preds_df.loc[preds_df[address_col].isin(input.selectize()), :]
    return selected_rows

@reactive.calc
def nowcast_similars():
    nowcast_subset = subset_nowcast()
    
    # Return empty DataFrame if nothing selected
    if nowcast_subset.empty:
        return pd.DataFrame()
    
    price_offset_pct = .10
    price_range_filter_bottom = nowcast_subset[nowcast_price_col].min()*(1-price_offset_pct)
    price_range_filter_top = nowcast_subset[nowcast_price_col].max()*(1+price_offset_pct)
    nowcast_price_offset_filter = (nowcast_subset[nowcast_price_col].between(price_range_filter_bottom, price_range_filter_top))
    similarly_priced = nowcast_subset.loc[nowcast_price_offset_filter, :]

    location_offset_pct = .10
    for location_col in location_cols:
        location_range_filter_bottom = similarly_priced[location_col].min()*(1-location_offset_pct)
        location_range_filter_top = similarly_priced[location_col].max()*(1+location_offset_pct)
        location_col_offset_filter = (similarly_priced[location_col].between(location_range_filter_bottom, location_range_filter_top))
        similarly_priced = similarly_priced.loc[location_col_offset_filter, :]

    similarly_priced = pd.concat([similarly_priced,nowcast_subset],axis=0)
    num_selected_rows = nowcast_subset.shape[0]
    
    # Handle potential division by zero
    if len(rank_cols) > 0:
        similarly_priced[rank_cols] = similarly_priced[rank_cols].rank(axis=0, ascending=False) / len(rank_cols)
    
    radar_chart_vals = similarly_priced.tail(num_selected_rows)
    
    return radar_chart_vals

# Function to check if any properties are selected
@reactive.calc
def has_selections():
    return len(input.selectize()) > 0

# Main layout with single page
# ui.panel_title("DC Real Estate Comparison")

# Property selection at the top
ui.input_selectize(
    id="selectize",
    label="Select homes to compare:",
    choices=[],
    multiple=True,
    options = {"placeholder": "Click here to enter address",
            'closeAfterSelect':True,
            'maxOptions':10,
            'openOnFocus':False}
)

# Create a layout with two columns
with ui.layout_columns(col_widths=[6, 6]):
    # Left column for radar chart
    with ui.card(full_screen=True):
        ui.card_header("Home Attributes Comparison")

        @render_plotly
        def radar():
            similars = nowcast_similars()
            if similars.empty:
                # Return empty figure if no selection
                fig = px.line_polar()
                # fig.update_layout(
                #     title="Select properties to see comparison"
                # )
                return fig
            
            try:
                # Safely drop columns and handle potential errors
                drop_cols = [col for col in [nowcast_price_col] + location_cols if col in similars.columns]
                similars = similars.drop(drop_cols, axis=1, errors='ignore')
                
                # Rename columns safely
                rename_cols = {k: v for k, v in pretty_names.items() if k in similars.columns}
                similars = similars.rename(columns=rename_cols)
                
                # Make sure address_col exists
                if address_col not in similars.columns:
                    return px.line_polar(title="Error: Address column not found")
                
                similars = similars.melt(id_vars=address_col, var_name='Attribute', value_name='Percentile')
                
                # Replace any NaN values before plotting
                similars['Percentile'] = similars['Percentile'].fillna(0)
                
                fig = px.line_polar(similars, r='Percentile', color=similars[address_col], 
                                    color_discrete_sequence=colorlist, 
                                    theta='Attribute', line_close=True)
                return fig
            except Exception as e:
                # Return an empty figure with error message if something goes wrong
                fig = px.line_polar()
                fig.update_layout(title=f"Error creating radar chart: {str(e)}")
                return fig

        @render.text
        def value():
            return "Percentiles of selected homes' attributes, as compared to homes with similar price and location."
    
    # Right column for map
    with ui.card(full_screen=True):
        ui.card_header("Home Locations")
        
        @render_plotly
        def dc_map():
            try:
                # Get selected properties if any
                selected_props = subset_nowcast()
                
                # Create an empty map of DC to start with
                # This will show when no properties are selected
                if not has_selections():
                    fig = px.scatter_mapbox(
                        # Empty DataFrame except for DC boundaries
                        pd.DataFrame({
                            'lat': [0],
                            'lon': [0],
                            'text': ['']
                        }),
                        lat='lat',
                        lon='lon',
                        text='text',
                        zoom=10
                    )
                
                else:
                    fig = px.scatter_mapbox(
                        # Empty DataFrame except for DC boundaries
                        selected_props,
                        lat="LATITUDE",
                        lon="LONGITUDE",
                        hover_name=address_col,
                        # hover_data=[nowcast_price_col, "GBA", "BEDRM"],
                        color=selected_props[address_col],
                        color_discrete_sequence=colorlist,
                        size_max=25,
                        hover_data=dict(LATITUDE=False,LONGITUDE=False),
                        zoom=10
                    )
                    
                # Update map layout - this runs even with no selections
                fig.update_layout(
                    mapbox_style="carto-positron",
                    # showlegend=False,
                    margin={"r": 0, "t": 0, "l": 0, "b": 0},
                    mapbox=dict(
                        center=dict(lat=38.895, lon=-77.036),  # Center on DC
                        zoom=10
                    )
                )
                
                # Add a message on the map when no properties are selected
                # if has_selections():
                    # If properties are selected, show all properties and highlight selected ones
                    # Get all properties with no NaN values
                    # all_props = preds_df.fillna({
                    #     'LATITUDE': 38.895,
                    #     'LONGITUDE': -77.036
                    # })
                    
                    # Add all properties as gray dots
                    # fig.add_trace(
                    #     px.scatter_mapbox(
                    #         all_props,
                    #         lat="LATITUDE",
                    #         lon="LONGITUDE",
                    #         hover_name=address_col,
                    #         hover_data=[nowcast_price_col, "GBA", "BEDRM"],
                    #         color_discrete_sequence=["gray"],
                    #         opacity=0.5,
                    #         size_max=10,
                    #     ).data[0]
                    # )
                    
                    # Add selected properties as red dots
                    # if not selected_props.empty:
                        # Ensure no NaN values
                        # selected_props = selected_props.fillna({
                        #     'LATITUDE': 38.895,
                        #     'LONGITUDE': -77.036
                        # })
                        # map_color_vals = colorlist[:len(selected_props)]
                        # print(map_color_vals)
                        # fig.add_trace(
                        #     px.scatter_mapbox(
                        #         selected_props,
                        #         lat="LATITUDE",
                        #         lon="LONGITUDE",
                        #         hover_name=address_col,
                        #         # hover_data=[nowcast_price_col, "GBA", "BEDRM"],
                        #         color=selected_props[address_col],
                        #         color_discrete_sequence=colorlist,
                        #         size_max=25,
                        #         hover_data=dict(LATITUDE=False,LONGITUDE=False)
                        #     ).data[0]
                        # )
                
                return fig
            except Exception as e:
                # Return a blank map with error message if something goes wrong
                fig = px.scatter_mapbox()
                fig.update_layout(
                    title=f"Error creating map: {str(e)}",
                    mapbox_style="open-street-map",
                    mapbox=dict(
                        center=dict(lat=38.895, lon=-77.036),
                        zoom=11
                    )
                )
                return fig

# Display property details table at the bottom
with ui.card():
    ui.card_header("Selected Home Details")
    
    @render.data_frame
    def nowcast_table():
        try:
            nowcast = subset_nowcast()
            similars = nowcast_similars().select_dtypes('number')
            if nowcast.empty:
                return render.DataGrid(pd.DataFrame({"Message": ["No homes selected. Use the dropdown above to select homes."]}))
            
            # Copy to avoid modifying the original data
            nowcast_display = nowcast.copy()
            
            # Rename columns safely
            rename_cols = {k: v for k, v in pretty_names.items() if k in nowcast_display.columns}
            nowcast_display = nowcast_display.rename(columns=rename_cols)
            similars = similars.rename(columns=rename_cols)
            similars = similars.drop(columns=['LATITUDE','LONGITUDE','Nowcast'])
            similars.columns = similars.columns + ' Percentile'
            
            # Format the price with error handling
            if nowcast_price_col in nowcast_display.columns:
                # Replace NaN with 0 before formatting
                # nowcast_display[nowcast_price_col] = nowcast_display[nowcast_price_col].fillna(0)
                nowcast_display[nowcast_price_col] = nowcast_display[nowcast_price_col].div(1e3).map('${:,.0f}K'.format)
                nowcast_display['Square Ft'] = nowcast_display['Square Ft'].map('{:,}'.format)
                nowcast_display = nowcast_display.drop(columns=['LATITUDE','LONGITUDE'])
            
            nowcast_display = pd.concat([nowcast_display,similars],axis=1)
            return render.DataGrid(nowcast_display, selection_mode="row", summary=False)
        except Exception as e:
            # Return a message if something goes wrong
            return render.DataGrid(pd.DataFrame({"Error": [str(e)]}))