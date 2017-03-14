var queue = function(key, val) {
    // Grab store, enforce it to be an object
    var q = store.get('queue');
    if(!_.isObject(q)) {
        q = {};
    }
    if(typeof(val) == 'undefined') {
        if(typeof(key) == 'undefined') {
            // No params, return queue
            return q;
        } else {
            // 'key' param, return property value
            if(!_.isArray(q[key])) {
                q[key] = [];
            }
            return q[key];
        }
    } else {
        // 'key' and 'val params, set property value
        q[key] = val;
        return store.set('queue', q);
    }
}

function openSocket() {
    var webSocket = 'ws://' + window.location.hostname + ':' + window.location.port + '/ws'
    var submitInterval;
    var $icon = $('#icon-no-websocket');

    if(window.WebSocket) {
        var ws = new WebSocket(webSocket);
    } else if(window.MozWebSocket) {
        var ws = MozWebSocket(webSocket);
    }

    ws.onopen = function() {
        var submit = function() {
            for(var key in queue()) {
                if(queue(key).length) {
                    ws.send(JSON.stringify(queue()));
                    return;
                }
            }
        };
        submitInterval = setInterval(submit, 5000);
        submit();

        $icon.stop().fadeOut();
    }

    ws.onmessage = function(e) {
        var data = JSON.parse(e.data);
        // Dequeue messages
        if(data.dequeue) {
            for(var key in data.dequeue) {
                var i = 0;
                while(i < queue(key).length) {
                    if(_.isEqual(queue(key)[i], data.dequeue[key])) {
                        var val = queue(key);
                        val.splice(i, 1);
                        queue(key, val);
                    } else {
                        i++;
                    }
                }
            }
        }
    }

    ws.onclose = function(e) {
        clearInterval(submitInterval);
        $icon.stop().fadeIn();
        setTimeout(openSocket, 1000);
    }
}

$(document).ready(function() {
    openSocket();
});



if(window.applicationCache) {
    window.applicationCache.addEventListener('downloading', function(e) {
        $('#cache-downloading').show().siblings().hide();
    }, false);
    window.applicationCache.addEventListener('progress', function(e) {
        $('#cache-downloading').show().siblings().hide();
    }, false);
    window.applicationCache.addEventListener('cached', function(e) {
        $('#cache-cached').show().siblings().hide();
    }, false);
    window.applicationCache.addEventListener('noupdate', function(e) {
        $('#cache-cached').show().siblings().hide();
    }, false);
    window.applicationCache.addEventListener('updateready', function(e) {
        $('#cache-updateready').show().siblings().hide();
    }, false);
    window.applicationCache.addEventListener('error', function(e) {
        $('#cache-error').show().siblings().hide();
        console.log(e);
    }, false);
}


function _scouting(ref, key) {
    console.log(typeof(ref));
    console.log(ref.nodeType);
    if(typeof(ref) == 'object' && ref.nodeType === 1) {
        var obj = serialize(ref);
        var scouting = queue(key);
        console.log(scouting);

        // Duplicate check
        for(var i = 0; i < scouting.length; i++) {
            if(_.isEqual(scouting[i], obj)) {
                console.log('dup');
                return;
            }
        }

        scouting.push(obj);
        queue(key, scouting);

        window.location.href = '/event/' + $(ref).find('[name="event_key"]').val();
    }
}

function scouting_match(ref) {
    _scouting(ref, 'scouting_match');
}

function scouting_pit(ref) {
    console.log(ref);
    _scouting(ref, 'scouting_pit');
}

function serialize(form) {
    var obj = {};
    $(form).find('input, select, textarea').not('[serialize="false"]').each(function() {
        var $input = $(this);
        var key = $input.attr('name') || $input.id;

        // Init arrays
        if(key.substring(key.length-2) == '[]') {
            if(!_.isArray(obj[key])) {
                obj[key.substring(0,key.length-2)] = [];
            }
        }

        // Skip inputs that shouldn't be recorded
        if($input.is('[type="checkbox"], [type="radio"]') && !$input.is(':checked')) {
            return;
        }

        // Record values
        if(key) {
            var val = $input.val();
            val = val && !isNaN(val) ? +val : val;
            if($input.is('[type="checkbox"]') && key.substring(key.length-2) == '[]') {
                // Handle multi-checkboxes
                obj[key.substring(0,key.length-2)].push(val);
            } else {
                // Handle everything else
                obj[key] = val;
            }
        }
    });
    console.log(obj);
    return obj;
}

function deserialize(form, data) {
    if(!_.isObject(data) && _.isString(data)) {
        data = JSON.parse(data);
    }
    console.log(data);

    for(var name in data) {
        // Massage values into an array
        var values = _.isArray(data[name]) ? data[name] : [data[name]];
        for(key in values) {
            // Find the correct element
            var $tag = $('[name="' + name + '"], [name="' + name + '[]"]').not(':disabled');
            if($tag.closest('.btn-group .btn.disabled').length) {
                continue;
            }
            if($tag.length > 1) {
                $tag = $tag.filter('[value="' + values[key] + '"]');
            }
            // Set the value appropriately
            if($tag.length) {
                if($tag.is('[type="checkbox"], [type="radio"]')) {
                    $tag.click();
                } else if($tag.is('.selectized')) {
                    $tag[0].selectize.setValue(values[key], true);
                } else {
                    $tag.val(values[key]);
                }
            }
        }
    }
}


// Initialize page
$(document).ready(function() {
    // btn-group behavior
    $('.btn-group[data-toggle="buttons"] > .btn').click(function(e) {
        var $btn = $(this);
        // btn-group disabling
        if($btn.is('.disabled')) {
            e.preventDefault();
            return false;
        }
        // btn-group styling
        $btn.children('input[type="checkbox"]').each(function() {
            if($(this).is(':checked')) {
                $btn.addClass('btn-primary');
            } else {
                $btn.removeClass('btn-primary');
            }
        });
        if($btn.children('input[type="radio"]').length) {
            $btn.addClass('btn-primary');
            var $btn_group = $().add($btn.closest('.btn-toolbar').children('.btn-group')).add($btn.closest('.btn-group'));
            $btn_group.children('.btn').not(this).removeClass('btn-primary active');
        }
    });

    // btn data-toggle subtract/add behavior
    $('.btn[data-toggle="subtract"], .btn[data-toggle="add"]').not('[data-target]').click(function() {
        // Allow data-target to be optional, find it and set it
        var $btn = $(this);
        if(!$btn.is('[data-target]')) {
            $btn.attr('data-target', $btn.closest('.input-group-btn').siblings('input').attr('name'));
         }
    });
    $('.btn[data-toggle="subtract"]').click(function() {
        var $input = $('[name="' + $(this).attr('data-target') + '"]');
        if($input.is('[min]') && parseInt($input.val())-1 < $input.attr('min')){ return; }
        $input.val(parseInt($input.val())-1);
    });
    $('.btn[data-toggle="add"]').click(function() {
        var $input = $('[name="' + $(this).attr('data-target') + '"]');
        if($input.is('[max]') && parseInt($input.val())+1 > $input.attr('max')){ return; }
        $input.val(parseInt($input.val())+1);
    });

    // Click the first tab on any nav-tabs without an active tab
    $('ul.nav-tabs').each(function() {
        if(!$(this).children('li.active').length) {
            $(this).children('li').children('a').first().click();
        }
    });
    // Click the appropriate nav-tab tab if there's a hash in URL
    if(window.location.hash && $('#'+window.location.hash.substring(1)+'.tab-page:not(.active)').length) {
        $('ul.nav-tabs > li > a[href="' + window.location.hash + '"]').click();
    }
    // Clicks on nav-tab tab will put it in the window location
    $('ul.nav-tabs > li > a[href^="#"]').click(function() {
        var href = $(this).attr('href');
        var $tab_page = $('#'+href.substring(1)+'.tab-page');
        if($tab_page.length && !$tab_page.hasClass('active')) {
            if(window.history.pushState) {
                window.history.pushState(null, null, href);
            } else {
                window.location.hash = href;
            }
        }
    });

    // Initialize selectize on all <select>s (if not IE because native form validation fails?)
    if(!detectIE()) {
        $('select').each(function() {
            var options = {
                'persist': false
            };
            $.each(this.attributes, function() {
                if(this.name.match(/^data-selectize-/)) {
                    options[this.name.replace(/^data-selectize-/,'')] = this.value;
                }
            });
            $(this).selectize(options);
        });
    }

    // Initialize DataTable on all Bootstrap <table>s
    $('table.table').filter(function(){return !$(this).find('*[colspan],*[rowspan]').length;}).each(function() {
        var $table = $(this);
        var table = $table.DataTable({
            'paging': false,  // disable paging
            'info': false,  // disable footer (not needed with no paging)
            'filter': false,  // disable filtering
            'order': [],  // disable initial sorting
            'fixedHeader': true
        });
        // Handle DataTable FixedHeader with nav-tab changes
        var $tab_toggle = $('a[href="#' + $table.closest('.tab-page').attr('id') + '"][data-toggle="tab"]');
        if($tab_toggle.length) {
            $tab_toggle.on('shown.bs.tab', function() {
                table.fixedHeader.enable();
            });
            $tab_toggle.on('hide.bs.tab', function() {
                table.fixedHeader.disable();
            });
            if(!$tab_toggle.is(':visible')) {
                table.fixedHeader.disable();
            }
        }
    });

    // Handle form key building
    $('[name="comp_level"], [name="match_number"], [name="set_number"]').attr('serialize', false).change(function() {
        if($('[name="comp_level"]').val() == 'qm') {
            $('[name="set_number"]').removeAttr('required').closest('.input-group').hide();
        } else {
            $('[name="set_number"]').attr('required','required').closest('.input-group').show();
        }
        $('[name="match_key"]').val(
            $('[name="event_key"]').val() + '_' +
            $('[name="comp_level"]').val() + $('[name="match_number"]').val() +
            ($('[name="set_number"]').is(':visible') ? 'm' + $('[name="set_number"]').val() : '')
        );
    });
    $('[name="team_number"]').attr('serialize', false).change(function() {
        $('[name="team_key"]').val('frc' + $(this).val());
    });
    // Handle form deserialization
    var $saved = $('[name="saved"]').attr('serialize', false);
    if($saved.length) {
        deserialize($saved.closest('form'), $saved.val());
    }
});


function loader(ref) {
    var $ref = $(ref);
    // Find dropdown button
    var $dropdown_menu = $ref.parents('.dropdown-menu');
    if($dropdown_menu.length) {
        $ref = $dropdown_menu.siblings('.dropdown-toggle');
    }
    // Disable
    if(!$ref.hasClass('disabled')) {
        if($ref.prop('tagName') == 'button') {
            $ref.attr('disabled', 'disabled');
        }
        $ref.addClass('disabled');
        $ref.find('.fa').addClass('fa-spin');
        $('body > .mask').show();
        return true;
    }
    return false;
}

// http://codepen.io/gapcode/pen/vEJNZN
function detectIE() {
    var ua = window.navigator.userAgent;
    var msie = ua.indexOf('MSIE ');
    if (msie > 0) {
        return parseInt(ua.substring(msie + 5, ua.indexOf('.', msie)), 10);
    }
    var trident = ua.indexOf('Trident/');
    if (trident > 0) {
        var rv = ua.indexOf('rv:');
        return parseInt(ua.substring(rv + 3, ua.indexOf('.', rv)), 10);
    }
    var edge = ua.indexOf('Edge/');
    if (edge > 0) {
        return parseInt(ua.substring(edge + 5, ua.indexOf('.', edge)), 10);
    }
    return false;
}