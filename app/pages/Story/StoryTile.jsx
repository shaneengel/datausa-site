import React, {Component} from "react";
import PropTypes from "prop-types";
import {Link} from "react-router";

import listify from "toCanon/listify";

import "./StoryTile.css";

class StoryTile extends Component {

  render() {
    const {formatters} = this.context;
    const {authors, date, featured, id, image, title} = this.props;

    return (
      <Link to={ `/story/${id}` } className={ `StoryTile ${ featured ? "featured" : "" } pt-card pt-elevation-0 pt-interactive` }>
        <div className="image" style={{backgroundImage: `url("${image}")`}}>
          { featured ? <div className="tag">Featured</div> : null }
        </div>
        <h2 className="title">{ title }</h2>
        <div className="footer">
          <div className="meta">
            <div className="author">Writted by { listify(authors.map(a => a.name)) }</div>
            <div className="date">{ formatters.Date(date) }</div>
          </div>
          <div className="action">Read More</div>
        </div>
      </Link>
    );

  }

}

StoryTile.contextTypes = {
  formatters: PropTypes.object
};

export default StoryTile;
