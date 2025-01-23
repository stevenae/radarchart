from pathlib import Path
from shiny import reactive
from shiny.express import input, render, ui
from shinywidgets import render_plotly
import plotly.express as px
import pandas as pd
import numpy as np
import os

ui.page_opts(fillable=True)

# Read nowcast for visualization
rank_cols = ['BATHRM','HF_BATHRM','BEDRM','GBA','YR_RMDL','EYB']
nowcast_price_col = 'nowcast_prediction'
address_col = 'ADDRESS'
location_cols = ['LATITUDE','LONGITUDE']
nowcast_select_cols = [*rank_cols,nowcast_price_col,address_col,*location_cols]
preds_df = pd.read_csv('nowcast_predictions.csv',
                       usecols=nowcast_select_cols)
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

ui.page_opts(title="Real-Steal.com", fillable=True)

@reactive.effect
def _():
    ui.update_selectize(
        id='selectize',
        choices=addresses,
        server=True
    )

@render.text
def value():
    return "Percentiles of selected homes' attributes, as compared to homes with similar (+/- 10%) price and location"

@reactive.calc
def subset_nowcast():
    selected_rows = preds_df.loc[preds_df[address_col].isin(input.selectize()), :]
    return selected_rows

@reactive.calc
def nowcast_similars():
    nowcast_subset = subset_nowcast()
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
    similarly_priced[rank_cols] = similarly_priced[rank_cols].rank(axis=0,ascending=False) / len(rank_cols)
    radar_chart_vals = similarly_priced.tail(num_selected_rows)
    return(radar_chart_vals)

with ui.navset_pill(id="tab"):
    with ui.nav_panel(title="Comparison",value='comparison_tab'):
        ui.input_selectize(
            id="selectize",
            label="Homes to compare:",
            choices=[],
            multiple=True,
            options = {"placeholder": "Click here to enter address",
                    'closeAfterSelect':True,
                    'maxOptions':10,
                    'openOnFocus':False}
        )
        @render_plotly
        def radar():
            similars = nowcast_similars()
            similars = similars.drop([nowcast_price_col,*location_cols], axis=1)
            similars = similars.rename(columns=pretty_names)
            similars = similars.melt(id_vars=address_col,var_name='Attribute',value_name='Percentile')
            fig = px.line_polar(similars, r='Percentile', color=address_col, theta='Attribute', line_close=True)
            return fig

        @render.data_frame
        def nowcast_table():
            nowcast = subset_nowcast()
            nowcast = nowcast.rename(columns=pretty_names)
            nowcast[nowcast_price_col] = nowcast[nowcast_price_col].div(1e3).map('${:,.0f}K'.format)
            return render.DataGrid(nowcast,
                selection_mode="row",
                summary=False)